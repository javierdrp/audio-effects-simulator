import dash


app = dash.Dash(__name__)

app.layout = dash.html.Div([

    dash.html.H1("Audio effects visualizer"),

    # store to send commands to ws through js
    dash.dcc.Store(id='ws-commands-store'),
    dash.html.Div(id='dummy-output'),

    # control panel
    dash.html.Div([
        dash.html.H3("Audio source"),
        dash.html.Button("Start microphone", id="start-mic-btn", n_clicks=0),
        dash.html.Button("Stop stream", id="stop-stream-btn", n_clicks=0),

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
    ],
    style={'width': '30%', 'float': 'left', 'padding': '10px'}),

    dash.html.Div([
        dash.dcc.Graph(id='time-domain-graph'),
        dash.dcc.Graph(id='spectrum-graph'),
    ],
    style={'width': '65%', 'float': 'right'})
])


# callbacks

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


dash.clientside_callback(
    """(command) => {
        if (command) window.dash_clientside.ws_sender.send_command(command);
        return window.dash_clientside.no_update;
    }""",
    dash.Output('dummy-output', 'children'),
    dash.Input('ws-commands-store', 'data'),
    prevent_initial_call=True
)


if __name__ == '__main__':
    app.run(debug=True)