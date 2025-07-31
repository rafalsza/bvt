import dash
import json
import yaml
import random
import docker
import dash_ag_grid as dag
from dash import dcc, html, ctx, Input, Output, State
from dash.dash_table import FormatTemplate
import dash_bootstrap_components as dbc
from types import SimpleNamespace
import pandas as pd
from sqlalchemy import create_engine
from pathlib import Path
from datetime import datetime
from dateutil.parser import parse
from web_layout.utils import money_color
from web_layout.dash_aggrid_table import *
from web_layout.modals import (
    container_status_modal,
    stop_loss_modal,
    set_coin_tp_modal,
    take_profit_modal,
)

P_BG_DARK = "p-1 bg-dark"
USER_DATA_ = "/user_data/"

# Create a Docker client
client = docker.from_env()

# Initialize the Dash app
app = dash.Dash(
    __name__,
    title="VT Bot",
    external_stylesheets=[dbc.themes.DARKLY, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
)


# Define the SQLite database connection function
def get_db_connection():
    database = "transactions.db"
    database_path = f"sqlite:///../../user_data/{database}"
    engine = create_engine(database_path)
    try:
        conn = engine.connect()
    except Exception as e:
        print(f"Could not connect to database. Error: {e}")
        conn = None
    return conn


user_data_path = str(Path(__file__).parent.parent.parent.as_posix())
interval = 10000
# path to bought coins file
coins_bought_file = user_data_path + USER_DATA_ + "coins_bought.json"
# path to the saved transactions history
profile_summary_file = user_data_path + USER_DATA_ + "profile_summary.json"
# path to config file
config_file = user_data_path + USER_DATA_ + "config.yml"

with open(config_file) as file:
    config = yaml.safe_load(file)

money = FormatTemplate.money(4)
percentage = FormatTemplate.percentage(2)


def generate_header_row():
    return dbc.Row(
        id="header-row",
        className="p-3 bg-dark border border-primary-subtle rounded-3",
        children=[
            dbc.Col(
                html.H1(
                    children=[
                        html.I(className="bi bi-currency-bitcoin text-warning me-3"),
                        "Binance Trading Bot",
                        html.I(className="bi bi-currency-bitcoin text-warning ms-3"),
                    ],
                    className="fw-bold text-primary text-center",
                ),
                className="col-md-6 ms-md-auto",
            ),
            dbc.Col(
                dbc.DropdownMenu(
                    id="menu",
                    label="Menu",
                    children=[
                        dbc.DropdownMenuItem("Stop", id="stop-container"),
                        dbc.DropdownMenuItem("Start", id="start-container"),
                        dbc.DropdownMenuItem("Restart", id="restart-container"),
                        dbc.DropdownMenuItem("Set Take profit", id="change-tp-menu"),
                        dbc.DropdownMenuItem("Set Stop Loss", id="change-sl-menu"),
                        dbc.DropdownMenuItem(
                            "Set Coin Take Profit", id="set-coin-tp-menu"
                        ),
                    ],
                    className="fw-bold text-primary",
                    align_end=True,
                ),
                className="col-md-1 ms-auto",
            ),
        ],
    )


def generate_current_session():
    return dbc.Row(
        id="current_session_row",
        className=P_BG_DARK,
        children=html.H3("Current Session", className="fw-bold text-primary text-left"),
    )


def generate_session_1():
    return dbc.Row(
        class_name="p-1 bg-dark border border-primary-subtle rounded-3 row row-cols-3",
        children=[
            dbc.Col(
                children=dcc.Markdown(
                    "<h4> Started:  | Running for: </h4>",
                    id="current_session_col_1",
                    dangerously_allow_html=True,
                    className="my-2 p-2 border-start border-5",
                ),
                md=4,
            ),
            dbc.Col(
                children=dcc.Markdown(
                    id="current_session_col_2",
                    dangerously_allow_html=True,
                    className="my-2 p-2 border-start border-5",
                ),
                md=4,
            ),
            dbc.Col(
                children=dcc.Markdown(
                    id="current_session_col_3", dangerously_allow_html=True
                ),
                md=4,
            ),
            dbc.Col(
                children=dcc.Markdown(
                    id="current_session_col_4", dangerously_allow_html=True
                ),
                md=4,
            ),
            dbc.Col(children="", md=4),
            dbc.Col(
                children=dcc.Markdown(
                    id="current_session_col_6", dangerously_allow_html=True
                ),
                md=4,
            ),
            dbc.Col(
                children=dcc.Markdown(
                    id="current_session_col_7", dangerously_allow_html=True
                ),
                md=4,
            ),
            dbc.Col(children="", md=4),
            dbc.Col(
                children=dcc.Markdown(
                    id="current_session_col_9", dangerously_allow_html=True
                ),
                md=4,
            ),
        ],
    )


def generate_all_time_data_header():
    return dbc.Row(
        className=P_BG_DARK,
        children=html.H3("All Time Data", className="fw-bold text-primary text-left"),
    )


def generate_all_time_data():
    return dbc.Row(
        className="p-3 mb-3 bg-dark border border-primary-subtle rounded-3 row row-cols-3",
        children=[
            dbc.Col(
                children=dcc.Markdown(
                    id="all_time_data_col_1", dangerously_allow_html=True
                ),
                md=4,
            ),
            dbc.Col(
                children=dcc.Markdown(
                    id="all_time_data_col_2", dangerously_allow_html=True
                ),
                md=4,
            ),
            dbc.Col(
                children=dcc.Markdown(
                    id="all_time_data_col_3", dangerously_allow_html=True
                ),
                md=4,
            ),
        ],
    )


def generate_trades():
    return dbc.Row(
        class_name="p-3 bg-dark border border-primary-subtle rounded-3",
        children=[
            html.Div(
                id="table_1_div",
                className=P_BG_DARK,
                children=[
                    dcc.Markdown(
                        "### **_Open Trades_** (Winning: <span class='text-secondary'>0</span> | Losing: <span "
                        "style='color:red;'>0</span>)",
                        id="open_trades_markdown",
                        className="fw-bold fst-italic",
                        dedent=True,
                        dangerously_allow_html=True,
                    ),
                    dag.AgGrid(
                        id="open_trades-table",
                        className="ag-theme-balham-dark",
                        columnDefs=columnDefs,
                        rowData=[],
                        columnSize="sizeToFit",
                        defaultColDef=defaultColDef,
                        dashGridOptions={
                            "rowSelection": "single",
                            "headerHeight": 50,
                        },
                        dangerously_allow_code=True,
                    ),
                ],
            ),
            html.Div(
                id="table_2_div",
                className="p-0 bg-dark",
                children=[
                    html.H3(
                        "Closed Trades", className="fw-bold fst-italic text-bg-dark"
                    ),
                    dag.AgGrid(
                        id="closed_trades-table",
                        className="ag-theme-balham-dark",
                        columnDefs=columnDefs_closed_trades,
                        rowData=[],
                        columnSize="sizeToFit",
                        defaultColDef=defaultColDef,
                        dashGridOptions=dashGridOption_closed_trades,
                        dangerously_allow_code=True,
                    ),
                ],
            ),
        ],
    )


# Define the layout of the app
app.layout = dbc.Container(
    id="main-container",
    className="container-lg my-5",
    fluid=True,
    children=[
        generate_header_row(),
        generate_current_session(),
        generate_session_1(),
        generate_all_time_data_header(),
        generate_all_time_data(),
        generate_trades(),
        dcc.Interval(
            id="interval-component", interval=interval
        ),  # update every x seconds
        take_profit_modal,
        stop_loss_modal,
        container_status_modal,
        set_coin_tp_modal,
    ],
)


# Define the callback function that updates the table
@app.callback(
    Output("open_trades-table", "rowData"),
    Output("closed_trades-table", "rowData"),
    Output("open_trades_markdown", "children"),
    Output("current_session_col_1", "children"),
    Output("current_session_col_2", "children"),
    Output("current_session_col_3", "children"),
    Output("current_session_col_4", "children"),
    Output("current_session_col_6", "children"),
    Output("current_session_col_7", "children"),
    Output("current_session_col_9", "children"),
    Output("all_time_data_col_1", "children"),
    Output("all_time_data_col_2", "children"),
    Output("all_time_data_col_3", "children"),
    Input("interval-component", "n_intervals"),
)
def update(n_intervals):
    with open(profile_summary_file) as f:
        profile_summary = json.load(f, object_hook=lambda d: SimpleNamespace(**d))

    with open(config_file) as file:
        config = yaml.safe_load(file)

    try:
        started = profile_summary.started
        start_date = datetime.fromisoformat(profile_summary.started)
        run_for = str(datetime.now() - start_date).split(".")[0]
    except ValueError as e:
        started = "NA"
        run_for = "NA"
        print(f"Error parsing date: {e}")
    except AttributeError as e:
        started = "NA"
        run_for = "NA"
        print(f"Attribute error: {e}")

    realised_color = money_color(profile_summary.realised_session_profit_incfees_perc)

    market_perf_color = (
        "danger" if profile_summary.all_time_market_profit <= 0 else "success"
    )
    market_link = (
        f'<a style="color: {market_perf_color}; text-decoration: none;" target="_blank" '
        f'href="https://www.binance.com/en/trade/BTCUSDT">'
        + str(profile_summary.all_time_market_profit)
        + "</a>"
    )

    unrealised_color = money_color(
        profile_summary.unrealised_session_profit_incfees_perc
    )

    if profile_summary.bot_paused:
        msg = "Buying Paused"
        color = "red"
    else:
        msg = "Buying Enabled"
        color = "success"

    try:
        next_check_time = parse(profile_summary.market_next_check_time)
        if next_check_time > datetime.now():
            next_check_time = profile_summary.market_next_check_time.split(" ")[
                1
            ].split(".")[0]
        else:
            next_check_time = "NA"
    except ValueError as e:
        next_check_time = "NA"
        print(f"Error parsing next check time: {e}")

    total_color = money_color(profile_summary.session_profit_incfees_total_perc)
    bot_perf_color = "danger" if profile_summary.bot_profit_perc < 0 else "success"

    # Connect to the database and retrieve the transaction data
    conn = get_db_connection()
    df = pd.read_sql_query("select * from transactions order by sell_time desc", conn)

    df["time_held"] = (
        pd.to_timedelta(df["time_held"]).dt.floor(freq="s").astype("string")
    )
    df["buy_time"] = pd.to_datetime(df["buy_time"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    # loop through each value in sell_time column
    for i in range(len(df)):
        # check if value already has milliseconds
        if df.loc[i, "sell_time"] is not None and "." not in df.loc[i, "sell_time"]:
            # add random milliseconds
            ms = random.randint(0, 999)
            df.loc[i, "sell_time"] += f".{ms:03d}"

    # convert to datetime
    df["sell_time"] = pd.to_datetime(df["sell_time"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    open_trades_columns = [
        "id",
        "buy_time",
        "symbol",
        "volume",
        "bought_at",
        "now_at",
        "change_perc",
        "profit_dollars",
        "time_held",
        "tp_perc",
        "sl_perc",
        "buy_signal",
    ]
    open_trades = df.loc[df["closed"] == 0, open_trades_columns]
    open_trades["id"] = list(range(1, len(open_trades) + 1))

    closed_trades_columns = [
        "id",
        "buy_time",
        "symbol",
        "volume",
        "bought_at",
        "sold_at",
        "change_perc",
        "profit_dollars",
        "sell_time",
        "time_held",
        "tp_perc",
        "sl_perc",
        "buy_signal",
        "sell_reason",
    ]
    closed_trades = df.loc[df["closed"] == 1, closed_trades_columns]
    closed_trades["id"] = list(range(1, len(closed_trades) + 1))

    winning_trades = open_trades[open_trades["change_perc"] > 0].shape[0]
    losing_trades = open_trades[open_trades["change_perc"] <= 0].shape[0]
    markdown_open_trades = f"<h3 class='fw-bold fst-italic'> Open Trades (Winning: <span class='text-success'>{winning_trades}</span> | Losing: <span class='text-danger'>{losing_trades}</span>)</h3>"

    current_session_col_1 = (
        f"#### Started: {started.split('.')[0]} | Running for: {run_for}"
    )
    current_session_col_2 = f"#### Current Trades: {profile_summary.current_holds}/{profile_summary.slots} ({profile_summary.current_exposure}/{profile_summary.invstment_total} {profile_summary.pair_with})"
    current_session_col_3 = f"<h4 class='my-2 p-2 border-{realised_color} border-start border-5'> Realised: <span class='text-center text-{realised_color}'>{profile_summary.realised_session_profit_incfees_perc:.2f}</span>% <p>Est: $<span class='text-center text-{realised_color}'>{profile_summary.realised_session_profit_incfees_total} </span>{profile_summary.pair_with}</p></h4>"
    current_session_col_4 = f"<h4 class='my-2 p-2 border-{market_perf_color} border-start border-5'> Market Performance: <span class='text-center text-{market_perf_color};'>{market_link}% </span> <span> (Since STARTED)</span></h4>"
    current_session_col_6 = f'<h4 class="my-2 p-2 border-{unrealised_color} border-start border-5"> Unrealised: <span class="text-{unrealised_color}">{profile_summary.unrealised_session_profit_incfees_perc:.5f}</span>% <p>Est: $<span class="text-{unrealised_color}">{profile_summary.unrealised_session_profit_incfees_total} </span>{profile_summary.pair_with}</p></h4>'
    current_session_col_7 = f'<h4 class="my-2 p-2 border-{color} border-start border-5"><span class="text-{color}">{msg}</span> <span> | Next market check: {next_check_time}</span></h4>'
    current_session_col_9 = f"<h4 class='my-2 p-2 border-{total_color} border-start border-5'> Total: <span class='text-center text-{total_color}'>{profile_summary.session_profit_incfees_total_perc:.5f}</span>% <p>Est: $<span class='text-{total_color}'>{profile_summary.session_profit_incfees_total}</span> {profile_summary.pair_with}</p></h4>"
    all_time_data_col_1 = f"<h4 class='bg-secondary my-2 p-2 border-{bot_perf_color} border-start border-5'> Bot Performance: <span class='text-center text-{bot_perf_color}'>{round(float(profile_summary.bot_profit_perc), 2)}</span>%<span> Est: $</span><span class='text-{bot_perf_color}'>{profile_summary.bot_profit} </span>{profile_summary.pair_with}</h4>"
    all_time_data_col_2 = f"<h4 class='bg-secondary my-2 p-2 border-start border-5'> Completed Trades: {profile_summary.trade_wins + profile_summary.trade_losses} (Wins: <span class='text-success'>{profile_summary.trade_wins}</span>, Losses: <span class='text-danger'>{profile_summary.trade_losses} </span>) | Win Ratio: {profile_summary.win_ratio}%</h4>"
    all_time_data_col_3 = f"<h4 class='bg-secondary my-2 p-2 border-start border-5'> Strategy: {config['trading_options']['SIGNALLING_MODULES'][1]} SL: {config['trading_options']['STOP_LOSS']}</h4>"

    return (
        open_trades.to_dict("records"),
        closed_trades.to_dict("records"),
        markdown_open_trades,
        current_session_col_1,
        current_session_col_2,
        current_session_col_3,
        current_session_col_4,
        current_session_col_6,
        current_session_col_7,
        current_session_col_9,
        all_time_data_col_1,
        all_time_data_col_2,
        all_time_data_col_3,
    )


@app.callback(
    Output("container-status-modal", "is_open"),
    Output("container-status-message-content", "children"),
    Input("stop-container", "n_clicks"),
    Input("start-container", "n_clicks"),
    Input("restart-container", "n_clicks"),
    Input("close-message-btn", "n_clicks"),
    State("container-status-modal", "is_open"),
)
def handle_container_status_actions(
    stop_clicks, start_clicks, restart_clicks, close_clicks, is_open
):
    if not any([stop_clicks, start_clicks, restart_clicks, close_clicks]):
        return is_open, ""

    container_name = "bvt_bot"
    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if triggered_id == "stop-container":
        container = client.containers.get(container_name)
        if container.status == "running":
            container.stop()
            return not is_open, "Container has been stopped."
        else:
            return is_open, "Container is already stopped."

    elif triggered_id == "start-container":
        container = client.containers.get(container_name)
        if container.status == "exited":
            container.start()
            return not is_open, "Container has been started."
        else:
            return is_open, "Container is already running."

    elif triggered_id == "restart-container":
        container = client.containers.get(container_name)
        if container.status == "running":
            container.restart()
            return not is_open, "Container has been restarted."
        else:
            return is_open, "Container is not running."

    elif triggered_id == "close-message-btn":
        return False, ""

    return is_open, ""


@app.callback(
    Output("stop-loss-modal", "is_open"),
    Output("stop-loss-input", "value"),  # Clear input field
    Input("change-sl-menu", "n_clicks"),
    Input("save-sl-btn", "n_clicks"),
    State("stop-loss-modal", "is_open"),
    State("stop-loss-input", "value"),
)
def handle_stop_loss_actions(
    change_sl_n_clicks, save_sl_n_clicks, is_open, new_sl_value
):
    if change_sl_n_clicks is None and save_sl_n_clicks is None:
        return is_open, dash.no_update

    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if triggered_id == "change-sl-menu":
        return not is_open, dash.no_update
    elif triggered_id == "save-sl-btn":
        if new_sl_value is not None:
            config["trading_options"]["STOP_LOSS"] = new_sl_value

            # Save the updated config back to the config file
            with open(config_file, "w") as file:
                yaml.dump(config, file, default_flow_style=False)

            container_name_or_id = "bvt_bot"
            container = client.containers.get(container_name_or_id)
            if container.status == "running":
                container.restart()

        return False, None
    else:
        return is_open, dash.no_update


# Take profit callback
@app.callback(
    Output("tp-modal", "is_open"),
    Output("tp-input", "value"),  # Clear input field
    Input("change-tp-menu", "n_clicks"),
    Input("save-tp-btn", "n_clicks"),
    State("tp-modal", "is_open"),
    State("tp-input", "value"),
)
def handle_tp_actions(change_tp_n_clicks, save_tp_n_clicks, is_open, new_tp_value):
    if change_tp_n_clicks is None and save_tp_n_clicks is None:
        return is_open, dash.no_update

    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if triggered_id == "change-tp-menu":
        return not is_open, dash.no_update
    elif triggered_id == "save-tp-btn":
        if new_tp_value is not None:
            config["trading_options"]["TAKE_PROFIT"] = new_tp_value

            # Save the updated config back to the config file
            with open(config_file, "w") as cfg_file:
                yaml.dump(config, cfg_file, default_flow_style=False)

            # # Read the current data from the JSON file
            # with open(coins_bought_file, "r") as json_file:
            #     coins_data = json.load(json_file)
            #
            # # Update the take_profit value for each coin in the JSON data
            # for coin in coins_data:
            #     coins_data[coin]["take_profit"] = new_tp_value
            #
            # # Write the updated data back to the JSON file
            # with open(coins_bought_file, "w") as json_file:
            #     json.dump(coins_data, json_file, indent=4)

            container_name_or_id = "bvt_bot"
            container = client.containers.get(container_name_or_id)
            if container.status == "running":
                container.restart()

        return False, None
    else:
        return is_open, dash.no_update


# Set a specific coin Take Profit callback
@app.callback(
    Output("set-coin-tp-modal", "is_open"),
    Output("set-coin-input", "value"),
    Output("set-coin-tp-input", "value"),
    Input("set-coin-tp-menu", "n_clicks"),
    Input("save-coin-tp-btn", "n_clicks"),
    State("set-coin-tp-modal", "is_open"),
    State("set-coin-input", "value"),
    State("set-coin-tp-input", "value"),
)
def handle_set_tp_coin(set_coin_tp_n_clicks, save_tp_n_clicks, is_open, coin, tp):
    if set_coin_tp_n_clicks is None and save_tp_n_clicks is None:
        return is_open, dash.no_update, dash.no_update

    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if triggered_id == "set-coin-tp-menu":
        return not is_open, dash.no_update, dash.no_update
    elif triggered_id == "save-coin-tp-btn":
        if coin and tp is not None:
            # Read the current data from the JSON file
            with open(coins_bought_file, "r") as json_file:
                coins_data = json.load(json_file)
            # Update the take_profit value for the specific coin in the coins_bought_file
            if coin in coins_data:
                coins_data[coin]["take_profit"] = int(tp)
                # Write the updated data back to the JSON file
                try:
                    with open(coins_bought_file, "w") as json_file:
                        json.dump(coins_data, json_file, indent=4)
                except Exception as e:
                    print("Error while writing JSON:", e)

            # Update the take_profit value for the specific coin in db
            conn = get_db_connection()
            try:
                query = f"UPDATE transactions SET tp_perc = {float(tp)} WHERE symbol = '{coin}' AND closed = 0"
                conn.exec_driver_sql(query)
                conn.commit()
                conn.close()
            except Exception as e:
                print("Error while updating database:", e)

        return False, None, None
    else:
        return is_open, dash.no_update, dash.no_update


# Run the app
if __name__ == "__main__":
    app.run_server(
        debug=True, host="0.0.0.0", port=8050, dev_tools_hot_reload_max_retry=50
    )
