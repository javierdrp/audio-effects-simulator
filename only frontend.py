import base64
import io

import numpy as np
import scipy.fft
import scipy.io
import dash
import plotly.graph_objs as go

# ---------------------------------------------------
# Funciones de ejemplo para DSP (muy simplificadas)
# ---------------------------------------------------

def generate_dummy_signal(fs=44100, duration=2.0, freq=440):
    """Genera una senoidal para pruebas si no hay audio cargado."""
    t = np.linspace(0, duration, int(fs * duration), endpoint=False)
    x = 0.5 * np.sin(2 * np.pi * freq * t)
    return x, fs

def apply_echo(x, fs, delay_ms=300, gain=0.4, repeats=3):
    delay_samples = int(fs * delay_ms / 1000)
    y = np.copy(x)
    for k in range(1, repeats + 1):
        start = delay_samples * k
        if start >= len(x):
            break
        y[start:] += (gain ** k) * x[:len(x) - start]
    # normalización simple para evitar clipping
    y = y / np.max(np.abs(y) + 1e-9)
    return y

def apply_distortion(x, drive=2.0, mode="soft"):
    x_d = drive * x
    if mode == "soft":
        y = np.tanh(x_d)
    else:  # hard clipping
        threshold = 0.6
        y = np.clip(x_d, -threshold, threshold)
    y = y / (np.max(np.abs(y)) + 1e-9)
    return y

def apply_reverb_simple(x, fs, room_size=0.3, mix=0.4):
    """
    Reverb muy simplificada: una especie de eco denso.
    Esto es SOLO para demo, no es una reverb realista.
    """
    delay_ms = 50
    repeats = 8
    delay_samples = int(fs * delay_ms / 1000)
    y = np.copy(x)
    for k in range(1, repeats + 1):
        start = delay_samples * k
        if start >= len(x):
            break
        gain = (room_size ** k)
        y[start:] += gain * x[:len(x) - start]
    y = y / (np.max(np.abs(y)) + 1e-9)
    return (1 - mix) * x + mix * y

def compute_spectrum(x, fs, n_fft=4096):
    """Devuelve frecuencias y magnitud en dB."""
    if len(x) < n_fft:
        # zero-padding
        x = np.pad(x, (0, n_fft - len(x)))
    X = scipy.fft.rfft(x[:n_fft])
    freqs = scipy.fft.rfftfreq(n_fft, 1/fs)
    mag = 20 * np.log10(np.abs(X) + 1e-9)
    return freqs, mag

# ---------------------------------------------------
# App Dash
# ---------------------------------------------------

app = dash.Dash(__name__)

app.layout = dash.html.Div(
    style={"display": "flex", "height": "100vh", "fontFamily": "Arial"},
    children=[
        # SIDEBAR ----------------------------------------------------
        dash.html.Div(
            style={
                "flex": "0 0 320px",
                "padding": "20px",
                "borderRight": "1px solid #ddd",
                "backgroundColor": "#fafafa",
                "overflowY": "auto",
            },
            children=[
                dash.html.H2("Simulador de efectos de audio", style={"marginBottom": "5px"}),
                dash.html.P(
                    "Explora eco, reverberación y distorsión mientras ves la señal "
                    "en el tiempo y el espectro.",
                    style={"fontSize": "0.9rem", "color": "#555"},
                ),

                dash.html.Hr(),

                dash.html.H4("1. Fuente de audio"),
                dash.dcc.RadioItems(
                    id="input-source",
                    options=[
                        {"label": "Archivo de audio", "value": "file"},
                        {"label": "Micrófono (futuro)", "value": "mic"},
                    ],
                    value="file",
                    labelStyle={"display": "block", "marginBottom": "4px"},
                ),

                dash.html.Div(
                    id="upload-container",
                    children=[
                        dash.dcc.Upload(
                            id="upload-audio",
                            children=dash.html.Div([
                                "Arrastra un archivo aquí o ",
                                dash.html.A("haz clic para seleccionar")
                            ]),
                            style={
                                "width": "100%",
                                "height": "60px",
                                "lineHeight": "60px",
                                "borderWidth": "1px",
                                "borderStyle": "dashed",
                                "borderRadius": "5px",
                                "textAlign": "center",
                                "marginBottom": "10px",
                                "backgroundColor": "white",
                            },
                            multiple=False
                        ),
                        dash.html.Div(
                            id="filename-info",
                            style={"fontSize": "0.85rem", "color": "#666"},
                        )
                    ]
                ),

                dash.html.Div(
                    id="mic-container",
                    style={"display": "none", "marginBottom": "10px"},
                    children=[
                        dash.html.Button(
                            "Grabar desde micrófono (placeholder)",
                            id="mic-record-btn",
                            n_clicks=0,
                            style={"width": "100%"}
                        ),
                        dash.html.P(
                            "La captura real de micrófono se puede implementar como "
                            "trabajo futuro usando componentes en JavaScript.",
                            style={"fontSize": "0.8rem", "color": "#777", "marginTop": "5px"},
                        ),
                    ]
                ),

                dash.html.Hr(),

                dash.html.H4("2. Efecto"),
                dash.dcc.Dropdown(
                    id="effect-type",
                    options=[
                        {"label": "Sin efecto", "value": "none"},
                        {"label": "Eco / Delay", "value": "echo"},
                        {"label": "Reverberación", "value": "reverb"},
                        {"label": "Distorsión", "value": "distortion"},
                    ],
                    value="none",
                    clearable=False,
                    style={"marginBottom": "10px"},
                ),

                dash.html.Div(id="effect-params-panel"),

                dash.html.Hr(),

                dash.html.H4("3. Opciones de visualización"),
                dash.dcc.Checklist(
                    id="plots-to-show",
                    options=[
                        {"label": " Dominio temporal", "value": "time"},
                        {"label": " Espectro de magnitud", "value": "freq"},
                    ],
                    value=["time", "freq"],
                    labelStyle={"display": "block"},
                    style={"marginBottom": "10px"},
                ),

                dash.dcc.RadioItems(
                    id="which-signals",
                    options=[
                        {"label": "Solo original", "value": "orig"},
                        {"label": "Solo procesada", "value": "proc"},
                        {"label": "Ambas", "value": "both"},
                    ],
                    value="both",
                    labelStyle={"display": "block"},
                ),

                dash.html.Hr(),

                dash.html.P(
                    "Consejo: cambia los parámetros del efecto y observa cómo se "
                    "deforma la señal y cómo se redistribuye la energía en frecuencia.",
                    style={"fontSize": "0.8rem", "color": "#555"},
                ),

                # Stores ocultos para compartir datos entre callbacks
                dash.dcc.Store(id="audio-original", storage_type="memory"),
                dash.dcc.Store(id="audio-processed", storage_type="memory"),
                dash.dcc.Store(id="audio-fs", storage_type="memory"),
            ],
        ),

        # MAIN PANEL -------------------------------------------------
        dash.html.Div(
            style={"flex": "1", "padding": "20px", "overflowY": "auto"},
            children=[
                dash.dcc.Tabs(
                    id="tabs",
                    value="tab-time",
                    children=[
                        dash.dcc.Tab(label="Tiempo", value="tab-time"),
                        dash.dcc.Tab(label="Espectro", value="tab-freq"),
                        dash.dcc.Tab(label="Comparativa", value="tab-compare"),
                    ],
                ),
                dash.html.Div(id="tab-content", style={"marginTop": "15px"}),

                dash.html.Hr(),

                dash.html.H4("Reproductores de audio"),
                dash.html.Div(
                    style={"display": "flex", "gap": "30px", "flexWrap": "wrap"},
                    children=[
                        dash.html.Div(
                            style={"flex": "1", "minWidth": "250px"},
                            children=[
                                dash.html.P("Original", style={"fontWeight": "bold"}),
                                dash.html.Audio(
                                    id="audio-player-original",
                                    controls=True,
                                    style={"width": "100%"},
                                ),
                            ],
                        ),
                        dash.html.Div(
                            style={"flex": "1", "minWidth": "250px"},
                            children=[
                                dash.html.P("Procesada", style={"fontWeight": "bold"}),
                                dash.html.Audio(
                                    id="audio-player-processed",
                                    controls=True,
                                    style={"width": "100%"},
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    ],
)

# ---------------------------------------------------
# Callbacks de interfaz (mostrar/ocultar paneles)
# ---------------------------------------------------

@app.callback(
    dash.Output("upload-container", "style"),
    dash.Output("mic-container", "style"),
    dash.Input("input-source", "value"),
)
def toggle_input_source(source):
    if source == "file":
        return (
            {"display": "block", "marginBottom": "10px"},
            {"display": "none"},
        )
    else:
        return (
            {"display": "none"},
            {"display": "block"},
        )

@app.callback(
    dash.Output("effect-params-panel", "children"),
    dash.Input("effect-type", "value"),
)
def update_effect_params_panel(effect):
    if effect == "echo":
        return dash.html.Div([
            dash.html.Label("Retardo (ms)"),
            dash.dcc.Slider(
                id="echo-delay",
                min=50, max=1000, step=10, value=300,
                tooltip={"placement": "bottom", "always_visible": False},
            ),
            dash.html.Label("Ganancia eco"),
            dash.dcc.Slider(
                id="echo-gain",
                min=0.1, max=0.9, step=0.05, value=0.4,
            ),
            dash.html.Label("Repeticiones"),
            dash.dcc.Slider(
                id="echo-repeats",
                min=1, max=10, step=1, value=3,
            ),
        ])
    elif effect == "reverb":
        return dash.html.Div([
            dash.html.Label("Tamaño de sala (room size)"),
            dash.dcc.Slider(
                id="reverb-room",
                min=0.1, max=0.9, step=0.05, value=0.3,
            ),
            dash.html.Label("Mezcla seco/húmedo"),
            dash.dcc.Slider(
                id="reverb-mix",
                min=0.0, max=1.0, step=0.05, value=0.4,
            ),
        ])
    elif effect == "distortion":
        return dash.html.Div([
            dash.html.Label("Drive (ganancia)"),
            dash.dcc.Slider(
                id="dist-drive",
                min=1.0, max=10.0, step=0.5, value=2.0,
            ),
            dash.html.Label("Tipo de distorsión"),
            dash.dcc.RadioItems(
                id="dist-mode",
                options=[
                    {"label": "Soft clipping", "value": "soft"},
                    {"label": "Hard clipping", "value": "hard"},
                ],
                value="soft",
                labelStyle={"display": "block"},
            ),
        ])
    else:
        return dash.html.Div([
            dash.html.P(
                "Selecciona un efecto para ver sus parámetros. "
                "Con 'Sin efecto' solo se visualiza la señal original.",
                style={"fontSize": "0.9rem", "color": "#666"},
            )
        ])

# ---------------------------------------------------
# Callback para cargar audio (por ahora: señal dummy)
# ---------------------------------------------------

@app.callback(
    dash.Output("audio-original", "data"),
    dash.Output("audio-fs", "data"),
    dash.Output("filename-info", "children"),
    dash.Input("upload-audio", "contents"),
    dash.State("upload-audio", "filename"),
    prevent_initial_call=True,
)
def load_audio(contents, filename):
    # Aquí iría la lógica real de decodificación de audio.
    # Para la visualización, si no quieres complicarte, puedes
    # limitarte a WAV mono y usar scipy.io.wavfile o soundfile.
    #
    # En este ejemplo, generamos una senoidal dummy para que
    # la interfaz funcione aunque aún no tengas DSP implementado.
    x, fs = generate_dummy_signal()
    info = f"Archivo cargado: {filename} (en este ejemplo se sustituye por una senoidal de prueba)."
    return x.tolist(), fs, info

# ---------------------------------------------------
# Callback para aplicar efecto a la señal
# ---------------------------------------------------

@app.callback(
    dash.Output("audio-processed", "data"),
    dash.Input("audio-original", "data"),
    dash.Input("audio-fs", "data"),
    dash.Input("effect-type", "value"),
    dash.Input("echo-delay", "value"),
    dash.Input("echo-gain", "value"),
    dash.Input("echo-repeats", "value"),
    dash.Input("reverb-room", "value"),
    dash.Input("reverb-mix", "value"),
    dash.Input("dist-drive", "value"),
    dash.Input("dist-mode", "value"),
)
def process_audio(
    x_data, fs,
    effect,
    echo_delay, echo_gain, echo_repeats,
    reverb_room, reverb_mix,
    dist_drive, dist_mode
):
    if x_data is None or fs is None:
        return None

    x = np.array(x_data, dtype=float)

    if effect == "echo":
        y = apply_echo(x, fs, delay_ms=echo_delay, gain=echo_gain, repeats=echo_repeats)
    elif effect == "reverb":
        y = apply_reverb_simple(x, fs, room_size=reverb_room, mix=reverb_mix)
    elif effect == "distortion":
        y = apply_distortion(x, drive=dist_drive, mode=dist_mode)
    else:
        y = x

    return y.tolist()

# ---------------------------------------------------
# Callback para contenido de las tabs (gráficas)
# ---------------------------------------------------

@app.callback(
    dash.Output("tab-content", "children"),
    dash.Input("tabs", "value"),
    dash.Input("audio-original", "data"),
    dash.Input("audio-processed", "data"),
    dash.Input("audio-fs", "data"),
    dash.Input("plots-to-show", "value"),
    dash.Input("which-signals", "value"),
)
def update_tab_content(tab, x_data, y_data, fs, plots_to_show, which_signals):
    if x_data is None or fs is None:
        return dash.html.Div("Carga un audio para empezar.", style={"padding": "10px"})

    x = np.array(x_data)
    t = np.arange(len(x)) / fs

    y = None
    if y_data is not None:
        y = np.array(y_data)

    show_time = "time" in plots_to_show
    show_freq = "freq" in plots_to_show

    children = []

    # Dominio temporal
    if show_time and tab in ["tab-time", "tab-compare"]:
        fig_time = go.Figure()
        if which_signals in ["orig", "both"]:
            fig_time.add_trace(go.Scatter(
                x=t, y=x, name="Original",
                line={"width": 1}
            ))
        if y is not None and which_signals in ["proc", "both"]:
            fig_time.add_trace(go.Scatter(
                x=t, y=y, name="Procesada",
                line={"width": 1}
            ))
        fig_time.update_layout(
            margin=dict(l=40, r=20, t=30, b=40),
            xaxis_title="Tiempo [s]",
            yaxis_title="Amplitud",
            height=350,
        )
        children.append(dash.html.H5("Señal en el tiempo"))
        children.append(dash.dcc.Graph(figure=fig_time))

    # Espectro
    if show_freq and tab in ["tab-freq", "tab-compare"]:
        freqs_x, mag_x = compute_spectrum(x, fs)
        fig_freq = go.Figure()
        if which_signals in ["orig", "both"]:
            fig_freq.add_trace(go.Scatter(
                x=freqs_x, y=mag_x, name="Original",
                line={"width": 1}
            ))
        if y is not None and which_signals in ["proc", "both"]:
            freqs_y, mag_y = compute_spectrum(y, fs)
            fig_freq.add_trace(go.Scatter(
                x=freqs_y, y=mag_y, name="Procesada",
                line={"width": 1}
            ))
        fig_freq.update_layout(
            margin=dict(l=40, r=20, t=30, b=40),
            xaxis_title="Frecuencia [Hz]",
            yaxis_title="Magnitud [dB]",
            height=350,
            xaxis_type="log",  # útil para ver más detalle en bajas frecuencias
        )
        children.append(dash.html.H5("Espectro de magnitud"))
        children.append(dash.dcc.Graph(figure=fig_freq))

    if not children:
        children = [dash.html.Div("Selecciona algún tipo de gráfica en el panel izquierdo.")]

    return children

# ---------------------------------------------------
# Callback para reproductores de audio (codificación WAV)
# ---------------------------------------------------

@app.callback(
    dash.Output("audio-player-original", "src"),
    dash.Output("audio-player-processed", "src"),
    dash.Input("audio-original", "data"),
    dash.Input("audio-processed", "data"),
    dash.Input("audio-fs", "data"),
)
def update_audio_players(x_data, y_data, fs):
    # Si aún no hay señal cargada, no mostramos nada
    if x_data is None or fs is None:
        return None, None

    # Pasamos la señal original a numpy
    x = np.array(x_data, dtype=float)

    # Normalizamos por seguridad y convertimos a int16 (formato típico WAV)
    if np.max(np.abs(x)) > 0:
        x_norm = x / np.max(np.abs(x))
    else:
        x_norm = x
    x_int16 = (x_norm * 32767).astype(np.int16)

    # Escribimos WAV en un buffer en memoria
    buf_orig = io.BytesIO()
    scipy.io.wavfile.write(buf_orig, int(fs), x_int16)
    buf_orig.seek(0)

    # Lo codificamos en base64
    b64_orig = base64.b64encode(buf_orig.read()).decode("ascii")
    src_orig = "data:audio/wav;base64," + b64_orig

    # Señal procesada (si existe)
    if y_data is not None:
        y = np.array(y_data, dtype=float)
        if np.max(np.abs(y)) > 0:
            y_norm = y / np.max(np.abs(y))
        else:
            y_norm = y
        y_int16 = (y_norm * 32767).astype(np.int16)

        buf_proc = io.BytesIO()
        scipy.io.wavfile.write(buf_proc, int(fs), y_int16)
        buf_proc.seek(0)

        b64_proc = base64.b64encode(buf_proc.read()).decode("ascii")
        src_proc = "data:audio/wav;base64," + b64_proc
    else:
        src_proc = None

    return src_orig, src_proc

if __name__ == "__main__":
    app.run(debug=True)
