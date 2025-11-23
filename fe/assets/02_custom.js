let ws;

function calculateSpectrum(signal, sampleRate) {
    const n_fft = signal.length;

    // hanning window to reduce spectral leakage
    const windowedSignal = new Array(n_fft);
    for (let i = 0; i < n_fft; i++) {
        const hanning = 0.5 * (1 - Math.cos(2 * Math.PI * i / (n_fft - 1)));
        windowedSignal[i] = signal[i] * hanning;
    }

    const fft = new FFT(n_fft);
    const complexSignal = fft.createComplexArray();
    fft.toComplexArray(windowedSignal, complexSignal);

    const complexSpectrum = fft.createComplexArray();
    fft.transform(complexSpectrum, complexSignal);

    const n_bins = n_fft / 2 + 1;
    const magnitudesDB = new Array(n_bins);
    const freqs = new Array(n_bins);

    for (let k = 0; k < n_bins; k++) {
        const real = complexSpectrum[2 * k];
        const imag = complexSpectrum[2 * k + 1];

        const magnitude = Math.sqrt(real * real + imag * imag);

        freqs[k] = k * (sampleRate / n_fft);

        magnitudesDB[k] = 20 * Math.log10(magnitude + 1e-9)  // add small value to prevent log(0);
    }

    return { freqs, magnitudesDB };
}

function connectWebSocket() {
    ws = new WebSocket("ws://localhost:8765");

    ws.onopen = (event) => console.log("Connected to audio backend");

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "plot_data") {
            // update plot data
            const n_points = data.input.length;
            const fs = data.sample_rate;
            const time_axis = Array.from({length: n_points}, (_, i) => i / fs);

            // update plots with plotly.react
            Plotly.react('time-domain-graph', [{
                x: time_axis,
                y: data.input,
                name: 'Input',
                type: 'scatter',
                line: {width: 1}
            }, {
                x: time_axis,
                y: data.output,
                name: 'Processed output',
                type: 'scatter',
                line: {width: 1}
            }], 
            {
                title: 'Time-domain signal',
                margin: {l: 40, r: 20, t: 40, b: 40},
                xaxis: {title: 'Tiempo (s)'},
                yaxis: {title: 'Amplitud', range: [-1, 1], autorange: false}
            });

            // calculate spectrum
            const spectrumInput = calculateSpectrum(data.input, fs);
            const spectrumOutput = calculateSpectrum(data.output, fs);

            Plotly.react('spectrum-graph', [{
                x: spectrumInput.freqs,
                y: spectrumInput.magnitudesDB,
                name: 'Input',
                type: 'scatter',
                line: {width: 1}
            }, {
                x: spectrumOutput.freqs,
                y: spectrumOutput.magnitudesDB,
                name: 'Processed output',
                type: 'scatter',
                line: {width: 1}
            }, {
                title: 'Signal spectrum',
                margin: {l: 40, r: 20, t: 40, b: 40},
                xaxis: {
                    title: 'Frequency (Hz)',
                    type: 'log',
                    range: [Math.log10(20), Math.log10(fs/2)]  // audible range
                },
                yaxis: {
                    title: 'Magnitude (dB)',
                    range: [-100, 0],
                    autorange: false
                }
            }]);
        }
    };

    ws.onclose = (event) => {
        console.log("Disconnected from backend. Attempting to reconnect in 3 seconds...");
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (error) => console.error("WebSocket error:", error);
}


window.addEventListener('load', connectWebSocket);

window.dash_clientside = Object.assign({}, window.dash_clientside, {
    ws_sender: {
        send_command: (command) => {
            if (ws && ws.readyState === WebSocket.OPEN)
                ws.send(JSON.stringify(command));
            else
                console.warn("WebSocket is not connected. Command not sent:", command);
        }
    }
});