'use strict';

let ws;

const PLOT_WINDOW_SIZE = 8192;  // 85ms window
const AUDIO_SAMPLE_RATE_DEFAULT = 48000;

// realtime ring buffers for plotting
let rtInputBuffer = new Array(PLOT_WINDOW_SIZE).fill(0);
let rtOutputBuffer = new Array(PLOT_WINDOW_SIZE).fill(0);

// file playback
let fullAudioOriginal = [];
let fullAudioProcessed = [];
let currentFileSampleRate = AUDIO_SAMPLE_RATE_DEFAULT;

let playbackRafId = null;

const COMMON_LAYOUT = {
    font: { family: 'Arial, sans-serif', size: 12, color: '#333' },
    plot_bgcolor: '#fcfcfc',
    paper_bgcolor: '#ffffff',
    margin: { l: 80, r: 20, t: 60, b: 60 },
    showlegend: true,
    legend: { x: 1, y: 1, xanchor: 'right' }
};

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

        const normalized = magnitude / n_fft;
        magnitudesDB[k] = 20 * Math.log10(normalized + 1e-9)  // convert to dB and add small value to prevent log(0);
    }

    return { freqs, magnitudesDB };
}

function pushToRingBuffer(buffer, newChunk) {
    // remove first N elements
    buffer.splice(0, newChunk.length);
    // add N elements to the end
    for (let i = 0; i < newChunk.length; i++) buffer.push(newChunk[i]);
}

function renderPlots(inputData, outputData, sampleRate, isRealTime) {

    if (typeof Plotly === 'undefined') return;
    
    const graphDiv1 = document.getElementById('time-domain-graph');
    const graphDiv2 = document.getElementById('spectrum-graph');
    
    if (!graphDiv1 || !graphDiv2) return;

    // time domain plot
    const time_axis = Array.from({length: inputData.length}, (_, i) => i / sampleRate);

    Plotly.react('time-domain-graph', [{
        x: time_axis,
        y: inputData,
        name: 'Original',
        type: 'scatter',
        line: {width: 2.0, color: '#002288'},
        opacity: 0.8
    }, {
        x: time_axis,
        y: outputData,
        name: 'Processed',
        type: 'scatter',
        line: {width: 1.5, color: '#dd2222'},
        opacity: 0.8
    }],
    {
        ...COMMON_LAYOUT,
        title: {
            text: 'Time Domain Analysis',
            y: 0.95,
            x: 0.5,
            xanchor: 'center',
            yanchor: 'top'
        },
        xaxis: {
            title: { text: 'Time window (s)', standoff: 15 },
            automargin: true,
            showgrid: true,
            gridcolor: '#eee',
            zeroline: true,
            zerolinecolor: '#999'
        },
        yaxis: {
            title: { text: 'Amplitude (normalized)', standoff: 15 },
            automargin: true,
            range: [-1.05, 1.05],
            autorange: false,
            showgrid: true,
            gridcolor: '#eee',
            zeroline: true,
            zerolinecolor: '#333'
        }
    });

    // frequency domain plot
    const specIn = calculateSpectrum(inputData, sampleRate);
    const specOut = calculateSpectrum(outputData, sampleRate);

    Plotly.react('spectrum-graph', [{
        x: specIn.freqs,
        y: specIn.magnitudesDB,
        name: 'Original',
        type: 'scatter',
        mode: 'lines',
        line: {width: 1.5, color: '#002288'},
        fill: 'tozeroy',
        fillcolor: 'rgba(31, 119, 180, 0.1)'
    }, {
        x: specOut.freqs,
        y: specOut.magnitudesDB,
        name: 'Processed',
        type: 'scatter',
        mode: 'lines',
        line: {width: 1.5, color: '#dd2222'}
    }],
    {
        ...COMMON_LAYOUT,
        title: {
            text: 'Frequency Spectrum (FFT)',
            y: 0.95,
            x: 0.5,
            xanchor: 'center',
            yanchor: 'top'
        },
        xaxis: {
            title: { text: 'Frequency (Hz)', standoff: 15 },
            automargin: true,
            type: 'log',
            range: [Math.log10(20), Math.log10(sampleRate / 2)],
            showgrid: true,
            gridcolor: '#eee'
        },
        yaxis: {
            title: { text: 'Magnitude (dBFS)', standoff: 15 },
            automargin: true,
            range: [-100, 0],
            autorange: false,
            showgrid: true,
            gridcolor: '#eee'
        }
    });


}

function updatePlotsForPlaybackTime(currentTime) {
    if (fullAudioOriginal.length === 0) return;

    const plotBlockSize = 2048;
    const startIndex = Math.floor(currentTime * currentFileSampleRate);

    if (startIndex + plotBlockSize > fullAudioOriginal.length) return;

    const originalSlice = fullAudioOriginal.slice(startIndex, startIndex + plotBlockSize);
    const processedSlice = fullAudioProcessed.slice(startIndex, startIndex + plotBlockSize);

    renderPlots(originalSlice, processedSlice, currentFileSampleRate, false);
}

function attemptAttachAudioListeners() {
    const playerOrig = document.getElementById('player-original');
    const playerProc = document.getElementById('player-processed');

    if (!playerOrig || !playerProc) {
        setTimeout(attemptAttachAudioListeners, 200);
        return;
    }
    if (playerOrig.dataset.hasListeners === "true") return;

    const handleStateChange = () => {
        const isAnyPlaying = !playerOrig.paused || !playerProc.paused;

        if (isAnyPlaying) {
            // Only start if not already running
            if (playbackRafId === null) {
                const loop = () => {
                    let activeTime = 0;
                    let playing = false;

                    if (!playerOrig.paused) {
                        activeTime = playerOrig.currentTime;
                        playing = true;
                    } else if (!playerProc.paused) {
                        activeTime = playerProc.currentTime;
                        playing = true;
                    }

                    if (playing) {
                        updatePlotsForPlaybackTime(activeTime);
                        playbackRafId = requestAnimationFrame(loop);
                    } else {
                        playbackRafId = null;
                    }
                };
                loop(); // Start loop
            }
        } else {
            // Stop only if NO player is playing
            if (playbackRafId !== null) {
                cancelAnimationFrame(playbackRafId);
                playbackRafId = null;
            }
        }
    };

    const singleUpdate = (e) => updatePlotsForPlaybackTime(e.target.currentTime);

    [playerOrig, playerProc].forEach(player => {
        player.addEventListener('play', handleStateChange);
        player.addEventListener('pause', handleStateChange);
        player.addEventListener('ended', handleStateChange);
        player.addEventListener('seeked', singleUpdate);   // Update immediately on release
        player.addEventListener('seeking', singleUpdate);  // Update while dragging slider
    });

    playerOrig.dataset.hasListeners = "true";
}

function connectWebSocket() {
    ws = new WebSocket("ws://localhost:8765");

    ws.onopen = (event) => {
        console.log("Connected to audio backend");

        attemptAttachAudioListeners();
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === "plot_data") {
            pushToRingBuffer(rtInputBuffer, data.input);
            pushToRingBuffer(rtOutputBuffer, data.output);
            renderPlots(rtInputBuffer, rtOutputBuffer, data.sample_rate, true);
        } else if (data.type === "file_processed") {
            fullAudioOriginal = data.original_samples;
            fullAudioProcessed = data.processed_samples;
            currentFileSampleRate = data.sample_rate;

            window.audioB64Original = data.original_b64;
            window.audioB64Processed = data.processed_b64;

            const playerOrig = document.getElementById('player-original');
            const playerProc = document.getElementById('player-processed');
            if (playerOrig) playerOrig.src = data.original_b64;
            if (playerProc) playerProc.src = data.processed_b64;

            updatePlotsForPlaybackTime(0);
            
            const resetButton = document.getElementById('loading-state-reset-trigger');
            if (resetButton) resetButton.click();
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
