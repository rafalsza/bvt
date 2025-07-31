import json
import yaml
import docker
from types import SimpleNamespace
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine
from load_css import local_css
from web_layout.utils import *
from dateutil.parser import parse
from pathlib import Path
from update_UI import update
from streamlit_option_menu import option_menu

user_data_path = str(Path(__file__).parent.parent.parent.as_posix())


@st.cache_resource(ttl=3600)
def get_db_connection():
    database = "transactions.db"
    try:
        return create_engine(f"sqlite:///../../user_data/{database}")
    except Exception as error:
        st.error((f"Error while connecting to {database}: ", error))
        print(f"Error while connecting to {database}: ", error)
        return None


# path to the saved transactions history
profile_summary_path = user_data_path + "/user_data/" + "profile_summary.json"
# path to config file
config_path = user_data_path + "/user_data/" + "config.yml"

with open(profile_summary_path) as f:
    profile_summary = json.load(f, object_hook=lambda d: SimpleNamespace(**d))

with open(config_path) as file:
    config = yaml.safe_load(file)

st.set_page_config(
    page_title="BVT Trading Bot",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)


with open("css/style.css") as f:
    st.markdown("<style>{}</style>".format(f.read()), unsafe_allow_html=True)
local_css("css/style.css")

client = docker.from_env()


def update_sl():
    if st.button("Update SL"):
        try:
            # Update the session_state variable
            new_sl = st.session_state.new_sl
            # Update the config
            config["trading_options"]["STOP_LOSS"] = new_sl
            # Print the config before and after update
            print("Config before update:")
            print(config["trading_options"]["STOP_LOSS"])
            with open(config_path, "w") as cfg_file:
                yaml.dump(config, cfg_file, default_flow_style=False)
            print("Config after update:")
            print(config["trading_options"]["STOP_LOSS"])
            st.success("SL updated successfully!")
        except ValueError:
            st.error("Please enter a valid number for SL")


# 5. Add on_change callback
def on_change(key):
    selection = st.session_state[key]
    container_name = "bvt_bot"
    container = client.containers.get(container_name)
    if selection == "Stop":
        st.warning("Stopping bot...")
        if container.status == "running":
            container.stop()
            st.warning("Bot stopped")
    elif selection == "Start":
        st.warning("Starting bot...")
        container = client.containers.get(container_name)
        if container.status == "exited":
            container.start()
            st.warning("Bot started")
    elif selection == "Restart":
        st.warning("Restarting container...")
        container = client.containers.get(container_name)
        if container.status == "running":
            container.restart()
    elif selection == "Set SL":
        new_sl = st.number_input(
            "Set SL", value=st.session_state.new_sl, key="new_sl", on_change=update_sl
        )
        container.restart()


# Create a session_state variable to store the input value
if "new_sl" not in st.session_state:
    st.session_state.new_sl = config["trading_options"]["STOP_LOSS"]

menu = option_menu(
    None,
    ["Home", "Restart", "Stop", "Start", "Set TP", "Set SL"],
    icons=["house", "bootstrap-reboot", "stop-circle", "play-btn"],
    menu_icon="cast",
    default_index=0,
    orientation="horizontal",
    on_change=on_change,
    key="menu_1",
    styles={
        "container": {"padding": "0!important", "background-color": "black"},
        "icon": {"color": "orange", "font-size": "25px"},
        "nav-link": {
            "font-size": "25px",
            "text-align": "left",
            "margin": "0px",
            "--hover-color": "DarkSlateGrey",
        },
        "nav-link-selected": {"background-color": "green"},
    },
)

# Title
"# Polynomial Regression Channel BVT Bot :skull: :japanese_ogre:"

"### **Current Session**"
kpi21, kpi22, kpi23 = st.columns(3)
with kpi21:
    try:
        started = profile_summary.started
        start_date = datetime.fromisoformat(profile_summary.started)
        run_for = str(datetime.now() - start_date).split(".")[0]
    except:
        started = "NA"
        run_for = "NA"
    st.markdown(
        f"<h4 style='text-align: left; margin-left: 30px;'> Started: {started.split('.')[0]} | Running for: {run_for}</h4>",
        unsafe_allow_html=True,
    )
    market_perf_color = (
        "red" if profile_summary.all_time_market_profit <= 0 else "green"
    )
    market_link = (
        f'<a style="color: {market_perf_color}; text-decoration: none;" target="_blank" '
        f'href="https://www.binance.com/en/trade/BTCUSDT">'
        + str(profile_summary.all_time_market_profit)
        + "</a>"
    )
    st.markdown(
        f"<h4 style='text-align: left; margin-left: 30px;'> Market Performance: <span style='text-align: center; color: {market_perf_color};'>{market_link}% </span> <span> (Since STARTED)</span></h3>",
        unsafe_allow_html=True,
    )
    if profile_summary.bot_paused:
        msg = "Buying Paused"
        color = "red"
    else:
        msg = "Buying Enabled"
        color = "green"

    try:
        next_check_time = parse(profile_summary.market_next_check_time)
        if next_check_time > datetime.now():
            next_check_time = profile_summary.market_next_check_time.split(" ")[
                1
            ].split(".")[0]
        else:
            next_check_time = "NA"
    except:
        next_check_time = "NA"
    st.markdown(
        f"<h4 style='text-align: left;  margin-left: 30px;'><span style='color: {color};'>{msg}</span> "
        f"<span> | Next market check: {next_check_time} </span> </h4>",
        unsafe_allow_html=True,
    )

with kpi22:
    st.markdown(
        f"<h4 style='text-align: left;  margin-left: 30px;'>Current Trades: {profile_summary.current_holds}/{profile_summary.slots} "
        f"({profile_summary.current_exposure}/{profile_summary.invstment_total} {profile_summary.pair_with})</h4>",
        unsafe_allow_html=True,
    )

with kpi23:
    realised_color = money_color(profile_summary.realised_session_profit_incfees_perc)

    st.markdown(
        f"<h4 style='text-align: left;  margin-left: 30px;'> Realised: &nbsp&nbsp&nbsp <span style='text-align: center; color: {realised_color};'>{profile_summary.realised_session_profit_incfees_perc:.5f}% Est: ${profile_summary.realised_session_profit_incfees_total} {profile_summary.pair_with}</span></h3>",
        unsafe_allow_html=True,
    )

    unrealised_color = money_color(
        profile_summary.unrealised_session_profit_incfees_perc
    )
    st.markdown(
        f"<h4 style='text-align: left;  margin-left: 30px;'> Unrealised: <span style='text-align: center; color: {unrealised_color};'>{profile_summary.unrealised_session_profit_incfees_perc:.5f}% Est: ${profile_summary.unrealised_session_profit_incfees_total} {profile_summary.pair_with}</span></h3>",
        unsafe_allow_html=True,
    )
    total_color = money_color(profile_summary.session_profit_incfees_total_perc)
    st.markdown(
        f"<h4 style='text-align: left;  margin-left: 30px;'> Total: &nbsp&nbsp&nbsp&nbsp&nbsp&nbsp&nbsp&nbsp&nbsp&nbsp&nbsp <span style='text-align: center; color: {total_color};'>{profile_summary.session_profit_incfees_total_perc:.5f}% Est: ${profile_summary.session_profit_incfees_total} {profile_summary.pair_with}</span></h3>",
        unsafe_allow_html=True,
    )

"### **All Time Data**"
kpi11, kpi12, kpi13 = st.columns(3)
with kpi11:
    bot_perf_color = "red" if profile_summary.bot_profit_perc < 0 else "green"
    st.markdown(
        f"<h4 style='text-align: left; margin-left: 30px;'> Bot Performance: <span style='text-align: center; color: {bot_perf_color};'>{round(float(profile_summary.bot_profit_perc), 2)}%</span> <span> Est: </span><span style='color: {bot_perf_color}';>${profile_summary.bot_profit} {profile_summary.pair_with}</span></h3>",
        unsafe_allow_html=True,
    )
with kpi12:
    st.markdown(
        f"<h4 style='text-align: left;  margin-left: 30px; padding-right: 0px'> Completed Trades: {profile_summary.trade_wins + profile_summary.trade_losses} (Wins: <span style='color:green'>{profile_summary.trade_wins}</span>, Losses: <span style='color:red'>{profile_summary.trade_losses} </span>) | Win Ratio: {profile_summary.win_ratio}%</h4>",
        unsafe_allow_html=True,
    )
with kpi13:
    st.markdown(
        f"<h4 style='text-align: left;  margin-left: 30px; padding-right: 0px'> Strategy: {config['trading_options']['SIGNALLING_MODULES'][1]} SL: {config['trading_options']['STOP_LOSS']}</h4>",
        unsafe_allow_html=True,
    )

st.markdown("<hr/>", unsafe_allow_html=True)

try:
    transactions_df = pd.read_sql_query(
        "select * from transactions order by sell_time desc", get_db_connection()
    )
    transactions_df["time_held"] = (
        pd.to_timedelta(transactions_df["time_held"])
        .dt.floor(freq="s")
        .astype("string")
    )
    transactions_df["buy_time"] = pd.to_datetime(
        transactions_df["buy_time"]
    ).dt.strftime("%Y-%m-%d %H:%M:%S")
    transactions_df["sell_time"] = pd.to_datetime(
        transactions_df["sell_time"]
    ).dt.strftime("%Y-%m-%d %H:%M:%S")

    open_columns = [
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
    open_trades = transactions_df.loc[transactions_df["closed"] == 0, open_columns]
    open_trades["id"] = list(range(1, len(open_trades) + 1))
    open_trades.rename(
        columns={
            "id": "Id",
            "buy_time": "Buy Time",
            "symbol": "Symbol",
            "volume": "Volume",
            "bought_at": "Bought at",
            "now_at": "Now at",
            "change_perc": "Change %",
            "profit_dollars": "Profit $",
            "time_held": "Time held",
            "tp_perc": "TP %",
            "sl_perc": "SL %",
            "buy_signal": "Buy Signal",
        },
        inplace=True,
    )

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
    closed_trades = transactions_df.loc[
        transactions_df["closed"] == 1, closed_trades_columns
    ]
    closed_trades["id"] = list(range(1, len(closed_trades) + 1))
    closed_trades.rename(
        columns={
            "id": "Id",
            "buy_time": "Buy Time",
            "symbol": "Symbol",
            "volume": "Volume",
            "bought_at": "Bought at",
            "sold_at": "Sold at",
            "change_perc": "Change %",
            "profit_dollars": "Profit $",
            "sell_time": "Sell time",
            "time_held": "Time held",
            "tp_perc": "TP %",
            "sl_perc": "SL %",
            "buy_signal": "Buy Signal",
            "sell_reason": "Sell Reason",
        },
        inplace=True,
    )

    st.markdown(
        f"### **_Open Trades_** (Winning: <span style='color:green;'>{open_trades[open_trades['Change %'] > 0].shape[0]}</span> | Losing: <span style='color:red;'>{open_trades[open_trades['Change %'] <= 0].shape[0]}</span>)",
        unsafe_allow_html=True,
    )

    st.dataframe(
        open_trades.style.hide(axis="index")
        .set_properties(subset=["Id"], **{"width": "100"})
        .format("{:.2f}%", subset=["Change %", "TP %", "SL %"])
        .apply(gray_background, axis=0)
        .map(color_negative_values, subset=["Change %", "Profit $"]),
        use_container_width=True,
        height=400,
        hide_index=True,
    )
    "### **_Closed Trades_**"
    st.dataframe(
        closed_trades.style.hide(axis="index")
        .set_properties(subset=["Id"], **{"width": "100"})
        .format("{:.2f}%", subset=["Change %", "TP %", "SL %"])
        .apply(gray_background, axis=0)
        .map(color_negative_values, subset=["Change %", "Profit $"]),
        use_container_width=True,
        height=400,
        hide_index=True,
    )

except Exception as e:
    print(e)
    pass
