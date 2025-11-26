'use strict';

let ws;

const PLOT_WINDOW_SIZE = 131072; // 2**17, 2.73secs 
const FFT_SIZE = 16384;
const AUDIO_SAMPLE_RATE_DEFAULT = 48000;
const NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

let rtInputBuffer = new Array(PLOT_WINDOW_SIZE).fill(0);
let rtOutputBuffer = new Array(PLOT_WINDOW_SIZE).fill(0);

let fullAudioOriginal = [];
let fullAudioProcessed = [];
let currentFileSampleRate = AUDIO_SAMPLE_RATE_DEFAULT;

let playbackRafId = null;

// --- FFT CACHE (Performance Optimization) ---
let cachedFFT = null;
let cachedFFTSize = 0;

function getFFT(size) {
    if (cachedFFT === null || cachedFFTSize !== size) {
        cachedFFT = new FFT(size);
        cachedFFTSize = size;
    }
    return cachedFFT;
}

const COMMON_LAYOUT = {
    font: { family: 'Arial, sans-serif', size: 12, color: '#333' },
    plot_bgcolor: '#fcfcfc',
    paper_bgcolor: '#ffffff',
    margin: { l: 40, r: 20, t: 40, b: 30 },
    showlegend: true,
    legend: { x: 1, y: 1, xanchor: 'right' }
};

// --- GUITAR-OPTIMIZED CHROMAGRAM ---
function calculateChroma(magnitudes, sampleRate, n_fft) {
    const chroma = new Array(12).fill(0);
    const n_bins = magnitudes.length;
    
    // Find peak for thresholding
    let maxMag = 0;
    for (let m of magnitudes) if (m > maxMag) maxMag = m;
    const threshold = maxMag * 0.15; 

    for (let k = 1; k < n_bins; k++) {
        const freq = k * (sampleRate / n_fft);
        const mag = magnitudes[k];

        // Filter out Rumble and High Harmonics
        if (freq < 70) continue; 
        
        let weighting = 1.0;
        if (freq > 800) weighting *= 0.5;
        if (freq > 1500) weighting *= 0.1;
        if (freq > 5000) continue; // Hard cut

        if (mag * weighting < threshold) continue;

        // MIDI Note calculation
        const midi = 12 * Math.log2(freq / 440) + 69;
        const nearestNote = Math.round(midi);
        const deviation = Math.abs(midi - nearestNote);

        // Relaxed Tuning Check:
        // We allow up to 0.45 semitone deviation because FFT bins are discrete.
        // This prevents "dropping" valid notes that land between bins.
        if (deviation > 0.50) continue;

        const pitchClass = nearestNote % 12;
        const idx = (pitchClass + 12) % 12;

        // Add energy
        chroma[idx] += mag * weighting; 
    }

    // Normalize
    const maxChroma = Math.max(...chroma) + 1e-9;
    for(let i=0; i<12; i++) {
        let val = chroma[i] / maxChroma;
        chroma[i] = val * val * val; // Cubic contrast
    }

    return chroma;
}

function calculateSpectrumAndChroma(signal, sampleRate) {
    const n_fft = signal.length;

    // Windowing
    const windowedSignal = new Array(n_fft);
    for (let i = 0; i < n_fft; i++) {
        // Blackman-Harris window (better side-lobe rejection than Hanning)
        const a0 = 0.35875, a1 = 0.48829, a2 = 0.14128, a3 = 0.01168;
        const w = a0 - a1*Math.cos(2*Math.PI*i/(n_fft-1)) + a2*Math.cos(4*Math.PI*i/(n_fft-1)) - a3*Math.cos(6*Math.PI*i/(n_fft-1));
        windowedSignal[i] = signal[i] * w;
    }

    const fft = getFFT(n_fft);
    const complexSignal = fft.createComplexArray();
    fft.toComplexArray(windowedSignal, complexSignal);

    const complexSpectrum = fft.createComplexArray();
    fft.transform(complexSpectrum, complexSignal);

    const n_bins = n_fft / 2 + 1;
    const magnitudesDB = new Array(n_bins);
    const magnitudesLin = new Array(n_bins); // Need linear for Chroma
    const freqs = new Array(n_bins);

    let peakMag = -Infinity;
    let peakFreq = 0;

    for (let k = 0; k < n_bins; k++) {
        const real = complexSpectrum[2 * k];
        const imag = complexSpectrum[2 * k + 1];
        const magnitude = Math.sqrt(real * real + imag * imag);
        
        freqs[k] = k * (sampleRate / n_fft);
        magnitudesLin[k] = magnitude;
        
        const normalized = magnitude / n_fft;
        magnitudesDB[k] = 20 * Math.log10(normalized + 1e-9);

        // Track Peak Frequency for Debugging
        // Ignore DC and Rumble < 60Hz
        if (freqs[k] > 60 && magnitudesDB[k] > peakMag) {
            peakMag = magnitudesDB[k];
            peakFreq = freqs[k];
        }
    }

    const chroma = calculateChroma(magnitudesLin, sampleRate, n_fft);

    return { freqs, magnitudesDB, chroma, peakFreq };
}

function pushToRingBuffer(buffer, newChunk) {
    buffer.splice(0, newChunk.length);
    for (let i = 0; i < newChunk.length; i++) buffer.push(newChunk[i]);
}

function renderPlots(inputData, outputData, sampleRate, isRealTime) {
    if (typeof Plotly === 'undefined') return;

    // --- 1. PREPARE TIME DOMAIN DATA (Decimated) ---
    // Downsample to keep the UI responsive while showing 2+ seconds of history
    const step = 40; // 131072 / 40 ~= 3200 points to render
    const plotLen = Math.floor(inputData.length / step);
    
    const tAxis = new Array(plotLen);
    const tInput = new Array(plotLen);
    const tOutput = new Array(plotLen);

    for (let i = 0, j = 0; i < inputData.length; i += step, j++) {
        tAxis[j] = i / sampleRate;
        tInput[j] = inputData[i];
        tOutput[j] = outputData[i];
    }

    // --- 2. PREPARE FREQUENCY DOMAIN DATA (Windowed) ---
    // We only FFT the most recent chunk to maintain speed and relevance
    const sliceStart = inputData.length - FFT_SIZE;
    const inputSlice = inputData.slice(sliceStart);
    const outputSlice = outputData.slice(sliceStart);

    const dIn = calculateSpectrumAndChroma(inputSlice, sampleRate);
    const dOut = calculateSpectrumAndChroma(outputSlice, sampleRate);


    // --- 3. RENDER ---
    
    // Time Domain
    Plotly.react('time-domain-graph', [
        { x: tAxis, y: tInput, name: 'Original', type: 'scatter', line: {width: 1, color: '#002288'}, opacity: 0.6 },
        { x: tAxis, y: tOutput, name: 'Processed', type: 'scatter', line: {width: 1, color: '#dd2222'}, opacity: 0.8 }
    ], {
        ...COMMON_LAYOUT,
        title: { text: 'Time Domain', y: 0.9, x: 0.5, xanchor: 'center', yanchor: 'top' },
        xaxis: { title: 'Time (s)', automargin: true, showgrid: false },
        yaxis: { range: [-1, 1], showgrid: true }
    });

    // Spectrum
    const peakLabel = `Spectrum (Peak: ${dIn.peakFreq.toFixed(1)} Hz)`;
    Plotly.react('spectrum-graph', [
        { x: dIn.freqs, y: dIn.magnitudesDB, name: 'Original', type: 'scatter', mode: 'lines', line: {width: 1, color: '#002288'}, fill: 'tozeroy', opacity: 0.3 },
        { x: dOut.freqs, y: dOut.magnitudesDB, name: 'Processed', type: 'scatter', mode: 'lines', line: {width: 1.5, color: '#dd2222'} }
    ], {
        ...COMMON_LAYOUT,
        title: { text: peakLabel, y: 0.9, x: 0.5, xanchor: 'center', yanchor: 'top' },
        xaxis: { type: 'log', range: [Math.log10(40), Math.log10(sampleRate / 2)], title: 'Hz' },
        yaxis: { range: [-80, 0], title: 'dB' }
    });

    // Chromagram
    Plotly.react('chroma-graph', [
        {
            r: dIn.chroma,
            theta: NOTES,
            name: 'Original',
            type: 'barpolar',
            marker: { color: '#002288', opacity: 0.4 }
        },
        {
            r: dOut.chroma,
            theta: NOTES,
            name: 'Processed',
            type: 'barpolar',
            marker: { color: '#dd2222', opacity: 0.7, line: { color: 'white', width: 1 } }
        }
    ], {
        ...COMMON_LAYOUT,
        title: { text: 'Pitch Class', y: 0.95 },
        polar: {
            radialaxis: { visible: false, range: [0, 1] },
            angularaxis: { direction: "clockwise", period: 12 }
        },
        showlegend: false
    });
}

function updatePlotsForPlaybackTime(currentTime) {
    if (fullAudioOriginal.length === 0) return;

    // This compensates for:
    // 1. The FFT window averaging (the transient needs to be inside the window)
    // 2. The time it takes for JS to calculate and Plotly to render the frame
    const LOOKAHEAD_SEC = 0.18; 

    // Use same large window for file playback consistency
    const plotBlockSize = PLOT_WINDOW_SIZE; 
    const currentSampleIndex = Math.floor((currentTime + LOOKAHEAD_SEC) * currentFileSampleRate);

    let originalSlice, processedSlice;
    const startIndex = currentSampleIndex - plotBlockSize;

    if (startIndex >= 0) {
        // Standard case: We have enough history
        // Slice from [Now - Window] to [Now]
        originalSlice = fullAudioOriginal.slice(startIndex, currentSampleIndex);
        processedSlice = fullAudioProcessed.slice(startIndex, currentSampleIndex);
    } else {
        // Start of file case: We don't have enough history yet
        // Create a zero-filled buffer and fill the end with what we have
        // This ensures the graph scrolls in from the right, just like Live Mode
        originalSlice = new Array(plotBlockSize).fill(0);
        processedSlice = new Array(plotBlockSize).fill(0);

        // Get all available data from 0 to Now
        const availableDataOrig = fullAudioOriginal.slice(0, currentSampleIndex);
        const availableDataProc = fullAudioProcessed.slice(0, currentSampleIndex);

        // Copy into the end of the buffer
        const offset = plotBlockSize - currentSampleIndex;
        for (let i = 0; i < currentSampleIndex; i++) {
            originalSlice[offset + i] = availableDataOrig[i];
            processedSlice[offset + i] = availableDataProc[i];
        }
    }

    renderPlots(originalSlice, processedSlice, currentFileSampleRate, false);
}

// ... (Audio Listener / Websocket code remains exactly the same) ...
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
            if (playbackRafId === null) {
                const loop = () => {
                    let activeTime = 0;
                    let playing = false;
                    if (!playerOrig.paused) { activeTime = playerOrig.currentTime; playing = true; } 
                    else if (!playerProc.paused) { activeTime = playerProc.currentTime; playing = true; }
                    if (playing) { updatePlotsForPlaybackTime(activeTime); playbackRafId = requestAnimationFrame(loop); } 
                    else { playbackRafId = null; }
                };
                loop();
            }
        } else {
            if (playbackRafId !== null) { cancelAnimationFrame(playbackRafId); playbackRafId = null; }
        }
    };
    const singleUpdate = (e) => updatePlotsForPlaybackTime(e.target.currentTime);
    [playerOrig, playerProc].forEach(player => {
        player.addEventListener('play', handleStateChange);
        player.addEventListener('pause', handleStateChange);
        player.addEventListener('ended', handleStateChange);
        player.addEventListener('seeked', singleUpdate);
        player.addEventListener('seeking', singleUpdate);
    });
    playerOrig.dataset.hasListeners = "true";
}

function connectWebSocket() {
    ws = new WebSocket("ws://localhost:8765");
    ws.onopen = (event) => { console.log("Connected"); attemptAttachAudioListeners(); };
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
    ws.onclose = () => setTimeout(connectWebSocket, 3000);
    ws.onerror = (e) => console.error(e);
}
window.addEventListener('load', connectWebSocket);
window.dash_clientside = Object.assign({}, window.dash_clientside, {
    ws_sender: { send_command: (c) => ws && ws.readyState === 1 && ws.send(JSON.stringify(c)) }
});
