import json

import dash_bootstrap_components as dbc
import yaml
from dash import dcc, html
from pathlib import Path

user_data_path = str(Path(__file__).parent.parent.parent.parent.as_posix())
config_file = user_data_path + "/user_data/" + "config.yml"
# path to bought coins file
coins_bought_file = user_data_path + "/user_data/" + "coins_bought.json"

with open(config_file) as file:
    config = yaml.safe_load(file)

# Read the coins data from the JSON file
with open(coins_bought_file, "r") as json_file:
    coins_data = json.load(json_file)
    coin_options = [
        {
            "label": html.Span(
                [coin],
                style={"color": "Gold", "font-size": 18, "background-color": "black"},
            ),
            "value": coin,
        }
        for coin in coins_data.keys()
    ]

set_coin_tp_modal = dbc.Modal(
    [
        dbc.ModalHeader("Set coin Take Profit"),
        dbc.ModalBody(
            [
                dcc.Dropdown(
                    id="set-coin-input",
                    className="text-white",
                    options=coin_options,  # Use the list of coin options
                    placeholder="Select a coin",
                    style={"marginRight": "10px", "backgroundColor": "black"},
                ),
                dbc.Input(
                    id="set-coin-tp-input",
                    className="text-primary bg-black",
                    type="number",
                    placeholder="Take Profit",
                    style={"marginRight": "10px"},
                ),
            ]
        ),
        dbc.ModalFooter(
            [
                dbc.Button("Update", id="save-coin-tp-btn", color="primary"),
                dbc.Button("Cancel", id="close-coin-tp-btn", color="secondary"),
            ]
        ),
    ],
    id="set-coin-tp-modal",
    size="md",
)

stop_loss_modal = dbc.Modal(
    [
        dbc.ModalHeader("Update Stop Loss"),
        dbc.ModalBody(
            dbc.Input(
                id="stop-loss-input",
                type="number",
                value=config["trading_options"]["STOP_LOSS"],
            )
        ),
        dbc.ModalFooter(
            [
                dbc.Button("Save", id="save-sl-btn", color="primary"),
                dbc.Button("Close", id="close-sl-btn", color="secondary"),
            ]
        ),
    ],
    id="stop-loss-modal",
    size="md",
)

take_profit_modal = dbc.Modal(
    [
        dbc.ModalHeader("Update Take Profit"),
        dbc.ModalBody(
            dbc.Input(
                id="tp-input",
                type="number",
                value=config["trading_options"]["TAKE_PROFIT"],
            )
        ),
        dbc.ModalFooter(
            [
                dbc.Button("Save", id="save-tp-btn", color="primary"),
                dbc.Button("Close", id="close-tp-btn", color="secondary"),
            ]
        ),
    ],
    id="tp-modal",
    size="md",
)

# Define the layout of the message modal
container_status_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle("Bot status")),
        dbc.ModalBody("", id="container-status-message-content"),
        dbc.ModalFooter(
            dbc.Button("Close", id="close-message-btn", n_clicks=0, className="ml-auto")
        ),
    ],
    id="container-status-modal",
    centered=True,
)
