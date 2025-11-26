import uuid
import dash
import copy


EFFECT_DEFAULTS = {
        'delay': {
            'feedback': 0.5,
            'delay_ms': 300,
            'mix_dry': 0.7,
            'mix_wet': 0.5,
            'offset_ms': 30
            },
        'reverb': {
            'rt60_s': 1.5,
            'mix_wet': 0.4,
            'mix_dry': 0.8,
            'damp': 0.3,
            'pre_delay_ms': 0.0
            },
        'gate': {
            'threshold_db': -30.0,
            'attack_ms': 10.0,
            'release_ms': 100.0
            },
        'spectral': {
            'threshold_db': -45.0,
            'reduction': 0.2  # Keep 20% of the noise (sounds more natural)
            },
        'octaver': {
            'semitones': -12.0, # Octave down by default
            'mix': 0.5
            }
        }

DEFAULT_PRESETS = {
    "Robot Voice": [
        {'effect_id': 'p1', 'type': 'gate', 'params': {'threshold_db': -30, 'attack_ms': 10, 'release_ms': 100}},
        {'effect_id': 'p2', 'type': 'octaver', 'params': {'semitones': -12, 'mix': 1.0}},
        {'effect_id': 'p3', 'type': 'delay', 'params': {'delay_ms': 120, 'feedback': 0.3, 'mix_wet': 0.3, 'mix_dry': 1.0, 'offset_ms': 10}}
    ],
    "Cathedral": [
        {'effect_id': 'p4', 'type': 'reverb', 'params': {'rt60_s': 4.0, 'mix_wet': 0.6, 'mix_dry': 0.6, 'damp': 0.2, 'pre_delay_ms': 20}}
    ],
    "Slapback Echo": [
        {'effect_id': 'p5', 'type': 'delay', 'params': {'delay_ms': 100, 'feedback': 0.0, 'mix_wet': 0.5, 'mix_dry': 1.0, 'offset_ms': 0}}
    ],
    "Clean Noise Removal": [
        {'effect_id': 'p6', 'type': 'spectral', 'params': {'threshold_db': -50, 'reduction': 0.1}},
        {'effect_id': 'p7', 'type': 'gate', 'params': {'threshold_db': -40, 'attack_ms': 5, 'release_ms': 200}}
    ]
}

app = dash.Dash(__name__)


def create_effect_card(effect_data, index, total_count):
    effect_id = effect_data["effect_id"]
    effect_type = effect_data["type"]
    params = effect_data["params"]

    control_configs = []
    if effect_type == 'delay':
        control_configs = [
                # (param_key, label, min, max, step)
                ('feedback', "Feedback", 0, 0.95, 0.01),
                ('delay_ms', "Delay time (ms)", 50, 1000, 1),
                ('mix_dry', "Dry mix", 0, 1, 0.01),
                ('mix_wet', "Wet mix", 0, 1, 0.01),
                ('offset_ms', "Stereo offset", 0, 1000, 1),
                ]
    elif effect_type == 'reverb':
        control_configs = [
                ('rt60_s', "60dB decay time (s)", 0.1, 10.0, 0.1),
                ('mix_dry', "Dry mix", 0, 1, 0.01),
                ('mix_wet', "Wet mix", 0, 1, 0.01),
                ('damp', "Damping", 0, 0.95, 0.01),
                ('pre_delay_ms', "Pre-delay (ms)", 0, 100, 1),
                ]
    elif effect_type == 'gate':
        control_configs = [
                ('threshold_db', "Threshold (dB)", -60, 0, 1),
                ('attack_ms', "Attack (ms)", 1, 500, 1),
                ('release_ms', "Release (ms)", 10, 1000, 10),
                ]
    elif effect_type == 'spectral':
        control_configs = [
                ('threshold_db', "Noise Threshold (dB)", -80, 0, 1),
                ('reduction', "Noise Floor (0=Silence, 1=Orig)", 0.0, 1.0, 0.05),
                ]
    elif effect_type == 'octaver':
        control_configs = [
                ('semitones', "Pitch Shift (Semitones)", -24, 24, 1),
                ('mix', "Mix (0=Dry, 1=Wet)", 0.0, 1.0, 0.05),
                ]

    controls_ui = []
    for param_key, label, min, max, step in control_configs:
        current_val = params.get(param_key, min)

        control_row = dash.html.Div([
            dash.html.Label(label, style={'fontWeight': 'bold', 'marginTop': '10px', 'display': 'block'}),
            dash.html.Div([
                dash.html.Div([
                    dash.dcc.Slider(
                        id={'type': 'effect-param-slider', 'effect_id': effect_id, 'param': param_key},
                        min=min,
                        max=max,
                        step=step,
                        value=current_val,
                        marks={min: str(min), max: str(max)},
                        tooltip={"placement": "bottom", "always_visible": False}
                        )
                    ], style={'flex': '1', 'paddingRight': '15px'}),
                dash.dcc.Input(
                    id={'type': 'effect-param-input', 'effect_id': effect_id, 'param': param_key},
                    type="number",
                    min=min,
                    max=max,
                    step=step,
                    value=current_val,
                    style={'width': '70px', 'height': '30px'}
                    )
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '5px'})
            ])
        controls_ui.append(control_row)

    up_visibility = "hidden" if (index == 0) else "visible"
    down_visibility = "hidden" if (index == total_count - 1) else "visible"

    return dash.html.Div(
            id={'type': 'effect-card-container', 'index': effect_id},
            className='effect-card',
            children=[
                dash.html.H3(f"{effect_type.title()} effect", style={'display': 'inline-block', 'marginRight': '20px'}),
                # UP BUTTON
                dash.html.Button(
                    "↑", id={'type': 'move-up-btn', 'index': index}, 
                    n_clicks=0,
                    style={'marginRight': '5px', 'padding': '5px 10px', 'cursor': 'pointer', 'visibility': up_visibility}
                    ),
                # DOWN BUTTON
                dash.html.Button(
                    "↓", id={'type': 'move-down-btn', 'index': index}, 
                    n_clicks=0,
                    style={'marginRight': '15px', 'padding': '5px 10px', 'cursor': 'pointer', 'visibility': down_visibility}
                    ),
                # DELETE BUTTON
                dash.html.Button("X", id={'type': 'delete-effect-btn', 'index': effect_id}, n_clicks=0),
                *controls_ui
                ],
            style={'border': '1px solid #ccc', 'padding': '15px', 'marginBottom': '15px', 'borderRadius': '8px', 'backgroundColor': '#f9f9f9'}
            )


app.layout = dash.html.Div([

    dash.dcc.Store(id='ws-commands-store'),
    dash.dcc.Store(id='loading-state-store'),
    dash.dcc.Store(id='effects-chain-store', data=[]),
    dash.dcc.Store(id='presets-store', storage_type='local', data=DEFAULT_PRESETS),

    dash.html.Div(id='dummy-output', style={'display': 'none'}),
    dash.html.Div(id='dummy-player-control', style={'display': 'none'}),
    dash.html.Div(id='dummy-player-visibility', style={'display': 'none'}),
    dash.html.Button(id='loading-state-reset-trigger', n_clicks=0, style={"display": "none"}),

    dash.html.Div([
        # control panel
        dash.html.Div([
            dash.html.H1("Audio effects visualizer"),
            dash.html.Hr(),
            dash.html.Hr(),
            dash.html.H2("Audio source"),
            dash.dcc.RadioItems(id="source-mode-selector", options=[
                {"label": " Microphone (live)", "value": "mic"},
                {"label": "WAV file", "value": "file"}
                ], value="mic", labelStyle={"display": "block"}),
            dash.html.Div(id="mic-controls", children=[
                dash.html.Button(
                    "▶ Start Microphone", 
                    id="start-mic-btn", 
                    n_clicks=0, 
                    className="btn-control btn-start"
                ),
                dash.html.Button(
                    "■ Stop Stream", 
                    id="stop-stream-btn", 
                    n_clicks=0, 
                    className="btn-control btn-stop"
                )
                ]),
            dash.html.Div(id="file-controls", children=[
                dash.dcc.Upload(
                    id="upload-audio",
                    children=dash.html.Div(["Drag and drop or ", dash.html.A("Select a .wav file")]),
                    style={
                        'width': '100%', 'height': '60px', 'lineHeight': '60px',
                        'borderWidth': '1px', 'borderStyle': 'dashed',
                        'borderRadius': '5px', 'textAlign': 'center', 'margin': '10px 0',
                        'cursor': 'pointer'
                        }
                    ),
                dash.html.Div(id="output-filename"),

                dash.html.Div(id='processing-status', children=[
                    dash.html.Div(className='loader-spinner'),  # CSS Class defined above
                    dash.html.Div("Processing...", style={'fontSize': '14px', 'color': '#666'})
                ], style={'display': 'none', 'textAlign': 'center', 'padding': '20px'}),

                dash.html.Hr(),
                dash.html.Label("Playback Monitor:", style={'fontWeight': 'bold'}),
                dash.dcc.RadioItems(
                    id='audio-monitor-source',
                    options=[
                        {'label': ' Original', 'value': 'Original'},
                        {'label': ' Processed', 'value': 'Processed'}
                        ],
                    value='Processed',
                    inline=True,
                    style={'marginBottom': '10px'}
                    ),
                dash.html.Div([
                    dash.html.Audio(id="player-original", controls=True, style={"width": "100%", "display": "none"}),
                    dash.html.Audio(id="player-processed", controls=True, style={"width": "100%", "display": "block"})
                    ])
                ]),


            dash.html.Hr(),
            dash.html.H2("Presets"),
            dash.html.Div([
                dash.dcc.Dropdown(
                    id='preset-selector', 
                    placeholder="Load a preset...",
                    style={'marginBottom': '10px'}
                ),
                dash.html.Div([
                    dash.dcc.Input(
                        id='preset-name-input', 
                        type='text', 
                        placeholder="Preset Name...",
                        style={
                            'flex': '2', 
                            'padding': '8px', 
                            'borderRadius': '5px', 
                            'border': '1px solid #ccc',
                            'marginRight': '5px'
                        }
                    ),
                    dash.html.Button(
                        "💾 Save", 
                        id='save-preset-btn', 
                        n_clicks=0,
                        style={
                            'flex': '1',
                            'backgroundColor': '#6c757d', 
                            'color': 'white', 
                            'border': 'none', 
                            'borderRadius': '5px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold'
                        }
                    )
                ], style={'display': 'flex', 'width': '100%'})
            ], style={'backgroundColor': '#f0f0f0', 'padding': '15px', 'borderRadius': '8px', 'marginBottom': '20px'}),

            dash.html.Hr(),
            dash.html.H2("Effects chain"),
            dash.html.Div(id='effects-chain-container', children=[]),
            dash.dcc.Dropdown(id='add-effect-dropdown', options=[
                {'label': 'Delay', 'value': 'delay'},
                {'label': 'Reverb', 'value': 'reverb'},
                {'label': 'Noise Gate', 'value': 'gate'},
                {'label': 'Spectral Filter', 'value': 'spectral'},
                {'label': 'Octaver', 'value': 'octaver'}
                ], placeholder='Select an effect to add...')

        ], style={
                # SIDEBAR STYLES
                'width': '30%', 
                'minWidth': '300px',
                'height': '100%', 
                'overflowY': 'auto', # Enables vertical scrolling for sidebar
                'padding': '20px', 
                'boxSizing': 'border-box',
                'borderRight': '1px solid #ddd',
                'backgroundColor': '#fcfcfc'
                }),

       
        dash.html.Div([
            
            # 1. TIME DOMAIN (Full Width, Top)
            dash.html.Div(
                dash.dcc.Graph(
                    id='time-domain-graph', 
                    style={'height': '100%', 'width': '100%'},
                    config={'responsive': True, 'displayModeBar': False} 
                ),
                style={'flex': '0 0 40%', 'marginBottom': '10px', 'minHeight': '0'} 
            ),

            # 2. ROW FOR SPECTRUM & CHROMA
            dash.html.Div([
                
                # SPECTRUM (Bottom Left)
                dash.html.Div(
                    dash.dcc.Graph(
                        id='spectrum-graph', 
                        style={'height': '100%', 'width': '100%'},
                        config={'responsive': True, 'displayModeBar': False}
                    ),
                    style={'flex': '1', 'minWidth': '0', 'marginRight': '5px'}
                ),

                # CHROMAGRAM (Bottom Right - NEW)
                dash.html.Div(
                    dash.dcc.Graph(
                        id='chroma-graph', 
                        style={'height': '100%', 'width': '100%'},
                        config={'responsive': True, 'displayModeBar': False}
                    ),
                    style={'flex': '1', 'minWidth': '0', 'marginLeft': '5px'}
                ),

            ], style={'flex': '1', 'display': 'flex', 'flexDirection': 'row', 'minHeight': '0'})

        ], style={
            'flex': '1',        
            'height': '100%',
            'display': 'flex',        
            'flexDirection': 'column',
            'overflow': 'hidden',     
            'padding': '15px',
            'boxSizing': 'border-box'
        })

    ], style={
            # MAIN CONTAINER STYLES
            'display': 'flex',
            'flexDirection': 'row',
            'height': '100vh',      # Forces container to be exactly viewport height
            'overflow': 'hidden',   # Prevents the whole page from scrolling
            'fontFamily': 'Arial, sans-serif'
            })
])


@app.callback(
        dash.Output('effects-chain-container', 'children'),
        dash.Input('effects-chain-store', 'data'),
        dash.State('effects-chain-container', 'children')
        )
def update_effects_chain_ui(chain_data, current_children):
    if not chain_data:
        # If data is empty but UI is not, we need to clear it
        if current_children: 
            return []
        return dash.no_update
    # prevent rerender when user moves a slider
    new_ids = [e['effect_id'] for e in chain_data]
    current_ids = [child['props']['id']['index'] for child in current_children]
    if new_ids == current_ids:
        raise dash.exceptions.PreventUpdate

    count = len(chain_data)
    return [create_effect_card(effect, i, count) for i, effect in enumerate(chain_data)]


@app.callback(
        dash.Output('effects-chain-store', 'data', allow_duplicate=True),
        dash.Output('ws-commands-store', 'data', allow_duplicate=True),
        dash.Output('add-effect-dropdown', 'value'),
        dash.Input('add-effect-dropdown', 'value'),
        dash.State('effects-chain-store', 'data'),
        prevent_initial_call=True
        )
def add_effect(effect_type, current_chain):
    if not effect_type:
        return dash.no_update, dash.no_update, None

    new_effect_id = str(uuid.uuid4())
    new_effect = {
            'effect_id': new_effect_id,
            'type': effect_type,
            'params': EFFECT_DEFAULTS[effect_type].copy() 
            }
    new_chain = current_chain + [new_effect]

    command = {
            'command': 'build_chain',
            'config': new_chain
            }

    return new_chain, command, ""


@app.callback(
        dash.Output('effects-chain-store', 'data', allow_duplicate=True),
        dash.Output('ws-commands-store', 'data', allow_duplicate=True),
        dash.Input({'type': 'delete-effect-btn', 'index': dash.ALL}, 'n_clicks'),
        dash.State('effects-chain-store', 'data'),
        prevent_initial_call=True
        )
def delete_effect(n_clicks, current_chain):
    if not dash.ctx.triggered_id:
        return dash.no_update, dash.no_update

    # prevent deletion when the callback is trigger by adding a new effect
    trigger_value = dash.ctx.triggered[0]['value']
    if not trigger_value or trigger_value == 0:
        return dash.no_update, dash.no_update

    effect_id_to_delete = dash.ctx.triggered_id['index']
    new_chain = [effect for effect in current_chain if effect['effect_id'] != effect_id_to_delete]
    command = {
            'command': 'build_chain',
            'config': new_chain
            }
    return new_chain, command


@app.callback(
        dash.Output('effects-chain-store', 'data', allow_duplicate=True),
        dash.Output('ws-commands-store', 'data', allow_duplicate=True),
        dash.Input({'type': 'move-up-btn', 'index': dash.ALL}, 'n_clicks'),
        dash.Input({'type': 'move-down-btn', 'index': dash.ALL}, 'n_clicks'),
        dash.State('effects-chain-store', 'data'),
        prevent_initial_call=True
        )
def reorder_effects(up_clicks, down_clicks, current_chain):
    if not current_chain or not dash.ctx.triggered:
        return dash.no_update, dash.no_update

    # check that a click actually happened (ignore initial render)
    trigger_value = dash.ctx.triggered[0]['value']
    if not trigger_value or trigger_value == 0:
        return dash.no_update, dash.no_update

    trigger_id = dash.ctx.triggered_id
    idx = trigger_id['index'] # type: ignore
    action = trigger_id['type'] # type: ignore

    new_chain = copy.deepcopy(current_chain)

    # swap logic
    if action == 'move-up-btn' and idx > 0:
        new_chain[idx], new_chain[idx-1] = new_chain[idx-1], new_chain[idx]
    elif action == 'move-down-btn' and idx < len(new_chain) - 1:
        new_chain[idx], new_chain[idx+1] = new_chain[idx+1], new_chain[idx]
    else:
        return dash.no_update, dash.no_update

    command = {'command': 'build_chain', 'config': new_chain}
    return new_chain, command


@app.callback(
        dash.Output({'type': 'effect-param-slider', 'effect_id': dash.MATCH, 'param': dash.MATCH}, 'value'),
        dash.Output({'type': 'effect-param-input', 'effect_id': dash.MATCH, 'param': dash.MATCH}, 'value'),
        dash.Input({'type': 'effect-param-slider', 'effect_id': dash.MATCH, 'param': dash.MATCH}, 'value'),
        dash.Input({'type': 'effect-param-input', 'effect_id': dash.MATCH, 'param': dash.MATCH}, 'value'),
        prevent_initial_call=True
        )
def sync_slider_and_input(slider_value, input_value):
    trigger_id = dash.ctx.triggered_id
    if not trigger_id:
        return dash.no_update, dash.no_update

    value = slider_value if trigger_id['type'] == 'effect-param-slider' else input_value
    return value, value


@app.callback(
        dash.Output('effects-chain-store', 'data', allow_duplicate=True),
        dash.Output('ws-commands-store', 'data', allow_duplicate=True),
        dash.Input({'type': 'effect-param-slider', 'effect_id': dash.ALL, 'param': dash.ALL}, 'value'),
        dash.State('effects-chain-store', 'data'),
        prevent_initial_call=True
        )
def update_parameter(value, current_chain):
    if not dash.ctx.triggered_id:
        return dash.no_update, dash.no_update

    # guard against race conditions when adding a new effect
    effect_id = dash.ctx.triggered_id['effect_id']
    if not effect_id or not current_chain or not any(eff['effect_id'] == effect_id for eff in current_chain):
        return dash.no_update, dash.no_update

    new_chain = copy.deepcopy(current_chain)
    param_name = dash.ctx.triggered_id['param']
    new_value = dash.ctx.triggered[0]['value']

    for effect in new_chain:
        if effect['effect_id'] == effect_id:
            effect['params'][param_name] = new_value
            break

    command = {
            'command': 'update_param',
            'effect_id': effect_id,
            'param': param_name,
            'value': new_value
            }

    return new_chain, command


@app.callback(
        dash.Output('upload-audio', 'disabled'),
        dash.Output('processing-status', 'style'),
        dash.Input('loading-state-store', 'data')
        )
def control_ui_during_load(data):
    is_busy = data.get('busy', False) if data else False
    
    # Toggle display between 'none' and 'block'
    spinner_style = {'display': 'block', 'textAlign': 'center', 'padding': '15px', 'backgroundColor': '#f0f8ff', 'borderRadius': '5px'}
    hidden_style = {'display': 'none'}
    
    return is_busy, (spinner_style if is_busy else hidden_style)


@app.callback(
        dash.Output('mic-controls', 'style'),
        dash.Output('file-controls', 'style'),
        dash.Input('source-mode-selector', 'value')
        )
def toggle_source_controls(mode):
    if mode == 'mic':
        return {"display": "flex"}, {"display": "none"}
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
        dash.Output('loading-state-store', 'data', allow_duplicate=True),
        dash.Input('loading-state-reset-trigger', 'n_clicks'),
        prevent_initial_call=True
        )
def reset_loading_state(n_clicks):
    return {'busy': False}


@app.callback(
    dash.Output('presets-store', 'data'),
    dash.Output('preset-selector', 'options'),
    dash.Output('preset-name-input', 'value'),
    dash.Input('save-preset-btn', 'n_clicks'),
    dash.Input('presets-store', 'data'), # Listen to init load
    dash.State('preset-name-input', 'value'),
    dash.State('effects-chain-store', 'data'),
)
def manage_presets(n_clicks, presets_data, new_name, current_chain):
    # Initialize if empty or first load
    if presets_data is None:
        presets_data = DEFAULT_PRESETS.copy()

    # If triggered by Save button
    if dash.ctx.triggered_id == 'save-preset-btn':
        if new_name and current_chain:
            # Save deep copy to ensure we don't store references
            presets_data[new_name] = copy.deepcopy(current_chain)
            # Clear input after save
            new_name = ""

    # Generate options for dropdown
    options = [{'label': name, 'value': name} for name in presets_data.keys()]
    
    return presets_data, options, new_name


@app.callback(
    dash.Output('effects-chain-store', 'data', allow_duplicate=True),
    dash.Output('ws-commands-store', 'data', allow_duplicate=True),
    dash.Output('preset-selector', 'value'),
    dash.Input('preset-selector', 'value'),
    dash.State('presets-store', 'data'),
    prevent_initial_call=True
)
def load_preset(selected_preset_name, presets_data):
    if not selected_preset_name or not presets_data:
        return dash.no_update, dash.no_update, dash.no_update
    
    if selected_preset_name in presets_data:
        # Get chain
        new_chain = copy.deepcopy(presets_data[selected_preset_name])
        
        # We must regenerate UUIDs to ensure unique keys for UI rendering
        # (Optional, but good practice if loading same preset twice allows unique modifications)
        for effect in new_chain:
            effect['effect_id'] = str(uuid.uuid4())

        command = {'command': 'build_chain', 'config': new_chain}
        return new_chain, command, None
    
    return dash.no_update, dash.no_update, dash.no_update


# command sender
dash.clientside_callback(
        """(command) => {
            if (command) window.dash_clientside.ws_sender.send_command(command);
            return window.dash_clientside.no_update;
            }""",
        dash.Output('dummy-output', 'children'),
        dash.Input('ws-commands-store', 'data'),
        prevent_initial_call=True
        )


# file processor
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
            return [{'busy': true}, `File uploaded: ${filename}`, null];
            }
        """,
        dash.Output('loading-state-store', 'data'),
        dash.Output('output-filename', 'children'),
        dash.Output('upload-audio', 'contents'),
        dash.Input('upload-audio', 'contents'),
        dash.State('upload-audio', 'filename'),
        prevent_initial_call=True
        )


# pause players on mic mode
dash.clientside_callback(
        """
        (mode) => {
            if (mode === 'mic') {
                const p1 = document.getElementById('player-original');
                const p2 = document.getElementById('player-processed');
                if (p1) p1.pause();
                if (p2) p2.pause();
                }
            return window.dash_clientside.no_update;
            }
        """,
        dash.Output('dummy-player-control', 'children'),
        dash.Input('source-mode-selector', 'value'),
        prevent_initial_call=True
        )


# source switch and player visibility toggle
dash.clientside_callback(
        """
        (source) => {
            const pOrig = document.getElementById('player-original');
            const pProc = document.getElementById('player-processed');

            if (!pOrig || !pProc) return window.dash_clientside.no_update;

            if (source === 'Original') {
                // Switching to Original
                // 1. Sync Time from Processed
                if (!Number.isNaN(pProc.duration)) {
                    pOrig.currentTime = pProc.currentTime;
                    }
                // 2. Sync Play State
                if (!pProc.paused) {
                    pOrig.play();
                    pProc.pause();
                    }
                // 3. Toggle Visibility
                pOrig.style.display = 'block';
                pProc.style.display = 'none';
                } else {
                    // Switching to Processed
                    // 1. Sync Time from Original
                    if (!Number.isNaN(pOrig.duration)) {
                        pProc.currentTime = pOrig.currentTime;
                        }
                    // 2. Sync Play State
                    if (!pOrig.paused) {
                        pProc.play();
                        pOrig.pause();
                        }
                    // 3. Toggle Visibility
                    pProc.style.display = 'block';
                    pOrig.style.display = 'none';
                    }

                return window.dash_clientside.no_update;
                }
        """,
        dash.Output('dummy-player-visibility', 'children'),
        dash.Input('audio-monitor-source', 'value'),
        prevent_initial_call=True
        )


if __name__ == '__main__':
    app.run(debug=True)
