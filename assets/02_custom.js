'use strict';

let ws;

// INCREASED SIZE for better bass resolution (2.9Hz per bin)
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

// --- FFT CACHE ---
let cachedFFT = null;
let cachedFFTSize = 0;

function getFFT(size) {
    if (cachedFFT === null || cachedFFTSize !== size) {
        cachedFFT = new FFT(size);
        cachedFFTSize = size;
    }
    return cachedFFT;
}

// --- PROFESSIONAL STYLING ---
const COLORS = {
    original: '#607d8b',  // Slate Blue (Input)
    processed: '#d35400', // Burnt Orange (Output)
    grid: '#f0f0f0',
    text: '#2c3e50',
    bg: '#ffffff'
};

const COMMON_LAYOUT = {
    font: { 
        family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif', 
        size: 11, 
        color: COLORS.text 
    },
    plot_bgcolor: COLORS.bg,
    paper_bgcolor: COLORS.bg,
    // Increased margins to ensure axis titles are visible
    margin: { l: 60, r: 20, t: 50, b: 50 },
    showlegend: true,
    legend: { 
        x: 1, 
        y: 1.15, 
        xanchor: 'right', 
        yanchor: 'top',
        orientation: 'h', 
        bgcolor: 'rgba(255,255,255,0)' 
    },
    xaxis: { showgrid: true, gridcolor: COLORS.grid, zeroline: false, automargin: true },
    yaxis: { showgrid: true, gridcolor: COLORS.grid, zeroline: false, automargin: true }
};

// --- DATA PROCESSING ---
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

        if (freq < 70) continue; 
        
        let weighting = 1.0;
        if (freq > 800) weighting *= 0.5;
        if (freq > 1500) weighting *= 0.1;
        if (freq > 5000) continue; 

        if (mag * weighting < threshold) continue;

        const midi = 12 * Math.log2(freq / 440) + 69;
        const nearestNote = Math.round(midi);
        const deviation = Math.abs(midi - nearestNote);

        if (deviation > 0.50) continue;

        const pitchClass = nearestNote % 12;
        const idx = (pitchClass + 12) % 12;

        chroma[idx] += mag * weighting; 
    }

    const maxChroma = Math.max(...chroma) + 1e-9;
    for(let i=0; i<12; i++) {
        let val = chroma[i] / maxChroma;
        chroma[i] = val * val * val; 
    }

    return chroma;
}

function calculateSpectrumAndChroma(signal, sampleRate) {
    const n_fft = signal.length;

    // Windowing
    const windowedSignal = new Array(n_fft);
    for (let i = 0; i < n_fft; i++) {
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
    const magnitudesLin = new Array(n_bins); 
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
    const step = 40; 
    const plotLen = Math.floor(inputData.length / step);
    
    const tAxis = new Array(plotLen);
    const tInput = new Array(plotLen);
    const tOutput = new Array(plotLen);

    for (let i = 0, j = 0; i < inputData.length; i += step, j++) {
        tAxis[j] = i / sampleRate;
        tInput[j] = inputData[i];
        tOutput[j] = outputData[i];
    }

    // --- 2. PREPARE FREQUENCY DOMAIN DATA ---
    const sliceStart = inputData.length - FFT_SIZE;
    const inputSlice = inputData.slice(sliceStart);
    const outputSlice = outputData.slice(sliceStart);

    const dIn = calculateSpectrumAndChroma(inputSlice, sampleRate);
    const dOut = calculateSpectrumAndChroma(outputSlice, sampleRate);


    // --- 3. RENDER ---
    
    // Time Domain
    Plotly.react('time-domain-graph', [
        { 
            x: tAxis, y: tOutput, 
            name: 'Processed', 
            type: 'scatter', 
            line: {width: 1, color: COLORS.processed, opacity: 0.7}, 
            hoverinfo: 'none' 
        },
        { 
            x: tAxis, y: tInput, 
            name: 'Original', 
            type: 'scatter', 
            line: {width: 1.2, color: COLORS.original, opacity: 0.7}, 
            hoverinfo: 'none' 
        }
    ], {
        ...COMMON_LAYOUT,
        title: { text: 'Time Domain', font: {size: 18}, x: 0, xanchor: 'left' },
        xaxis: { 
            ...COMMON_LAYOUT.xaxis,
            title: { text: 'Time (s)', font: { size: 12 } } 
        },
        yaxis: { 
            ...COMMON_LAYOUT.yaxis,
            range: [-1, 1], 
            title: { text: 'Amplitude', font: { size: 12 } }
        }
    });

    // Spectrum
    const peakLabel = `Spectrum (Peak: ${dIn.peakFreq.toFixed(1)} Hz)`;
    Plotly.react('spectrum-graph', [
        { 
            x: dIn.freqs, y: dIn.magnitudesDB, 
            name: 'Original', 
            type: 'scatter', 
            mode: 'lines', 
            line: {width: 1.5, color: COLORS.original, opacity: 0.7}
        },
        { 
            x: dOut.freqs, y: dOut.magnitudesDB, 
            name: 'Processed', 
            type: 'scatter', 
            mode: 'lines', 
            line: {width: 1.8, color: COLORS.processed, opacity: 0.7} 
        }
    ], {
        ...COMMON_LAYOUT,
        title: { text: peakLabel, font: {size: 18}, x: 0, xanchor: 'left' },
        xaxis: { 
            ...COMMON_LAYOUT.xaxis,
            type: 'log', 
            range: [Math.log10(40), Math.log10(sampleRate / 2)], 
            title: { text: 'Frequency (Hz)', font: { size: 12 } }
        },
        yaxis: { 
            ...COMMON_LAYOUT.yaxis,
            range: [-80, 0], 
            title: { text: 'Relative magnitude (dB)', font: { size: 12 } }
        }
    });
    // Chromagram
    Plotly.react('chroma-graph', [
        {
            r: dIn.chroma,
            theta: NOTES,
            name: 'Original',
            type: 'barpolar',
            // Use explicit RGBA for robust transparency
            marker: { color: 'rgba(96, 125, 139, 0.5)', line: { color: 'rgba(96, 125, 139, 1)', width: 1 } }
        },
        {
            r: dOut.chroma,
            theta: NOTES,
            name: 'Processed',
            type: 'barpolar',
            // Use explicit RGBA for robust transparency
            marker: { color: 'rgba(211, 84, 0, 0.6)', line: { color: 'white', width: 1 } }
        }
    ], {
        ...COMMON_LAYOUT,
        title: { text: 'Pitch Class', font: {size: 18}, x: 0.5, xanchor: 'center' }, 
        polar: {
            radialaxis: { visible: false, range: [0, 1] },
            angularaxis: { direction: "clockwise", period: 12, tickfont: {size: 10} },
            bgcolor: COLORS.bg
        },
        showlegend: false,
        margin: { ...COMMON_LAYOUT.margin, t: 50 } 
    });
    }

function updatePlotsForPlaybackTime(currentTime) {
    if (fullAudioOriginal.length === 0) return;

    // Latency compensation (~120ms ahead)
    const LOOKAHEAD_SEC = 0.12; 
    const plotBlockSize = PLOT_WINDOW_SIZE; 
    
    let currentSampleIndex = Math.floor((currentTime + LOOKAHEAD_SEC) * currentFileSampleRate);

    // Clamp to end
    if (currentSampleIndex > fullAudioOriginal.length) {
        currentSampleIndex = fullAudioOriginal.length;
    }

    let originalSlice, processedSlice;
    const startIndex = currentSampleIndex - plotBlockSize;

    if (startIndex >= 0) {
        originalSlice = fullAudioOriginal.slice(startIndex, currentSampleIndex);
        processedSlice = fullAudioProcessed.slice(startIndex, currentSampleIndex);
    } else {
        originalSlice = new Array(plotBlockSize).fill(0);
        processedSlice = new Array(plotBlockSize).fill(0);
        const availableLen = Math.min(currentSampleIndex, fullAudioOriginal.length);
        const availableDataOrig = fullAudioOriginal.slice(0, availableLen);
        const availableDataProc = fullAudioProcessed.slice(0, availableLen);
        const offset = plotBlockSize - availableLen;
        for (let i = 0; i < availableLen; i++) {
            originalSlice[offset + i] = availableDataOrig[i];
            processedSlice[offset + i] = availableDataProc[i];
        }
    }

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
    const backendUrl = "wss://YOUR-BACKEND-NAME.onrender.com";  // "ws://localhost:8765"
    console.log("Connecting to:", backendUrl);
    ws = new WebSocket(backendUrl);
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
