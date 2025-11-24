import dash


app = dash.Dash(__name__)

app.layout = dash.html.Div([

    dash.html.H1("Audio effects visualizer"),

    dash.dcc.Store(id='ws-commands-store'),
    dash.dcc.Store(id='loading-state-store'),
    dash.html.Div(id='dummy-output'),
    dash.html.Button(id='loading-state-reset-trigger', n_clicks=0, style={"display": "none"}),

    # control panel
    dash.html.Div([
        dash.html.H3("Audio source"),
        dash.dcc.RadioItems(id="source-mode-selector", options=[
            {"label": " Microphone (live)", "value": "mic"},
            {"label": "WAV file", "value": "file"}
        ], value="mic", labelStyle={"display": "block"}),
        dash.html.Div(id="mic-controls", children=[
            dash.html.Button("Start microphone", id="start-mic-btn", n_clicks=0),
            dash.html.Button("Stop stream", id="stop-stream-btn", n_clicks=0)
        ]),
        dash.html.Div(id="file-controls", children=[
            dash.dcc.Upload(
                id="upload-audio",
                children=dash.html.Div(["Drag and drop or ", dash.html.A("Select a .wav file")]),
                style={
                    'width': '100%', 'height': '60px', 'lineHeight': '60px',
                    'borderWidth': '1px', 'borderStyle': 'dashed',
                    'borderRadius': '5px', 'textAlign': 'center', 'margin': '10px 0'
                }
            ),
            dash.html.Div(id="output-filename"),
            dash.dcc.Loading(id='loading-spinner', type='circle', children=dash.html.Div(id='loading-output'))
        ]),

        dash.html.Hr(),
        dash.html.H3("Effects chain"),
        dash.html.Button("Build chain (delay -> reverb)", id="build-chain-btn"),

        dash.html.Hr(),
        dash.html.H3("Delay (ID: 'delay1')"),
        dash.html.Label("Feedback (0-0.95)"),
        dash.dcc.Slider(id="delay-feedback-slider", min=0, max=0.95, step=0.01, value=0.5),
        dash.html.Label("Delay time (ms)"),
        dash.dcc.Slider(id="delay-time-slider", min=50, max=1000, step=5, value=300),

        dash.html.Hr(),
        dash.html.H3("Reverb (ID: 'reverb1')"),
        dash.html.Label("60dB decay time (s)"),
        dash.dcc.Slider(id="reverb-rt60-slider", min=0.1, max=10.0, step=0.1, value=1.5),
        dash.html.Label("Wet mix"),
        dash.dcc.Slider(id="reverb-mix-slider", min=0.0, max=1.0, step=0.05, value=0.4),
    ], style={'width': '30%', 'float': 'left', 'padding': '10px'}),

    dash.html.Div([
        dash.html.H3("Audio playback"),
        dash.html.Div([
            dash.html.Div([
                dash.html.Label("Original audio"),
                dash.html.Audio(id="player-original", controls=True, style={"width": "100%"})
            ], style={"flex": 1, "minWidth": "250px"}),
            dash.html.Div([
                dash.html.Label("Processed audio"),
                dash.html.Audio(id="player-processed", controls=True, style={"width": "100%"})
            ], style={"flex": 1, "minWidth": "250px"})
        ], style={"display": "flex", "gap": "20px", "flexWrap": "wrap"}),

        dash.html.Hr(),
        dash.html.H3("Real-time visualization"),
        dash.dcc.Graph(id='time-domain-graph'),
        dash.dcc.Graph(id='spectrum-graph'),
    ], style={'width': '65%', 'float': 'right'})
])


@app.callback(
    dash.Output('upload-audio', 'disabled'),
    dash.Output('build-chain-btn', 'disabled'),
    dash.Output('delay-feedback-slider', 'disabled'),
    dash.Output('delay-time-slider', 'disabled'),
    dash.Output('reverb-rt60-slider', 'disabled'),
    dash.Output('reverb-mix-slider', 'disabled'),
    dash.Output('loading-spinner', 'children'),
    dash.Input('loading-state-store', 'data')
)
def control_ui_during_load(data):
    is_busy = data.get('busy', False) if data else False
    return [is_busy] * 6 + [None]


@app.callback(
    dash.Output('mic-controls', 'style'),
    dash.Output('file-controls', 'style'),
    dash.Input('source-mode-selector', 'value')
)
def toggle_source_controls(mode):
    if mode == 'mic':
        return {"display": "block"}, {"display": "none"}
    else:
        return {"display": "none"}, {"display": "block"}
    

@app.callback(
    dash.Output('ws-commands-store', 'data', allow_duplicate=True),
    dash.Input('source-mode-selector', 'value'),
    prevent_initial_call=True
)
def stop_mic_on_mode_change(mode):
    if mode == 'file':
        return {"command": "stop"}
    return dash.no_update


@app.callback(
    dash.Output('ws-commands-store', 'data', allow_duplicate=True),
    dash.Input('start-mic-btn', 'n_clicks'),
    prevent_initial_call=True
)
def start_mic(n_clicks):
    return {'command': 'start_mic'}


@app.callback(
    dash.Output('ws-commands-store', 'data', allow_duplicate=True),
    dash.Input('stop-stream-btn', 'n_clicks'),
    prevent_initial_call=True
)
def stop_stream(n_clicks):
    return {'command': 'stop'}


@app.callback(
    dash.Output('ws-commands-store', 'data', allow_duplicate=True),
    dash.Input('build-chain-btn', 'n_clicks'),
    prevent_initial_call=True
)
def build_chain(n_clicks):
    chain_config = [
        {
            "id": "delay1",
            "type": "delay",
            "params": { "max_delay_ms": 1500, "mix_dry": 0.7, "mix_wet": 0.5 }
        },
        {
            "id": "reverb1",
            "type": "reverb",
            "params": { "mix_dry": 0.8, "mix_wet": 0.4 }
        }
    ]
    return {'command': 'build_chain', 'config': chain_config}


# update parameters
@app.callback(
    dash.Output('ws-commands-store', 'data', allow_duplicate=True),
    dash.Input('delay-feedback-slider', 'value'),
    prevent_initial_call=True
)
def update_delay_feedback(value):
    return {
        'command': 'update_param',
        'effect_id': 'delay1',
        'param': 'feedback',
        'value': value
    }


@app.callback(
    dash.Output('ws-commands-store', 'data', allow_duplicate=True),
    dash.Input('delay-time-slider', 'value'),
    prevent_initial_call=True
)
def update_delay_time(value):
    return {
        'command': 'update_param',
        'effect_id': 'delay1',
        'param': 'delay_ms',
        'value': value
    }


@app.callback(
    dash.Output('ws-commands-store', 'data', allow_duplicate=True),
    dash.Input('reverb-rt60-slider', 'value'),
    prevent_initial_call=True
)
def update_reverb_rt60(value):
    return {
        'command': 'update_param',
        'effect_id': 'reverb1',
        'param': 'rt60',
        'value': value
    }


@app.callback(
    dash.Output('ws-commands-store', 'data', allow_duplicate=True),
    dash.Input('reverb-mix-slider', 'value'),
    prevent_initial_call=True
)
def update_reverb_mix(value):
    return {
        'command': 'update_param',
        'effect_id': 'reverb1',
        'param': 'mix_wet',
        'value': value
    }


@app.callback(
    dash.Output('loading-state-store', 'data', allow_duplicate=True),
    dash.Input('loading-state-reset-trigger', 'n_clicks'),
    prevent_initial_call=True
)
def reset_loading_state(n_clicks):
    return {'busy': False}


dash.clientside_callback(
    """(command) => {
        if (command) window.dash_clientside.ws_sender.send_command(command);
        return window.dash_clientside.no_update;
    }""",
    dash.Output('dummy-output', 'children'),
    dash.Input('ws-commands-store', 'data'),
    prevent_initial_call=True
)


dash.clientside_callback(
    """
    (contents, filename) => {
        if (!contents) return [window.dash_clientside.no_update, "No file loaded"];
        
        const command = {
            'command': 'process_file',
            'contents': contents,
            'filename': filename
        }
        
        window.dash_clientside.ws_sender.send_command(command);
        return [{'busy': true}, `Processing: ${filename}`];
    }
    """,
    dash.Output('loading-state-store', 'data'),
    dash.Output('output-filename', 'children'),
    dash.Input('upload-audio', 'contents'),
    dash.State('upload-audio', 'filename'),
    prevent_initial_call=True
)


if __name__ == '__main__':
    app.run(debug=True)