import json
import yaml
from types import SimpleNamespace
from load_css import local_css
from datetime import datetime
import streamlit as st
import pandas as pd
import time
from sqlalchemy import create_engine
from web_layout.utils import *
# from web_layout.data import *
from dateutil.parser import parse
from pathlib import Path
# from update_UI import update

user_data_path = str(Path(__file__).parent.parent.parent.as_posix())

# @st.cache(ttl=360, max_entries=3, allow_output_mutation=True)
@st.cache(allow_output_mutation=True)
def get_db_connection():
    database = "transactions.db"
    try:
        return create_engine(f"sqlite:///../../user_data/{database}")
    except Exception as error:
        st.error((f"Error while connecting to {database}: ", error))
        print(f"Error while connecting to {database}: ", error)
        return None


# path to the saved transactions history
profile_summary_file = user_data_path + "/user_data/" + "profile_summary.json"

# path to config file
config_file = user_data_path + "/user_data/" + "config.yml"

# with open(profile_summary_file) as f:
#     profile_summary = json.load(f, object_hook=lambda d: SimpleNamespace(**d))

with open(config_file) as file:
    config = yaml.safe_load(file)

st.set_page_config(
    page_title="BVT Trading Bot",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)

local_css("css/style.css")
# Title
"# Polynomial Regression Channel BVT Bot :skull: :japanese_ogre:"

# creating a single-element container.
placeholder = st.empty()
# near real-time / live feed simulation
while True:
    
    # while True:
    # for seconds in range(200):

    try:
        with open(profile_summary_file) as f:
            profile_summary = json.load(f, object_hook=lambda d: SimpleNamespace(**d))

        transactions_df = pd.read_sql_query(
            "select * from transactions order by sell_time desc", get_db_connection()
        )
        transactions_df["time_held"] = (
            pd.to_timedelta(transactions_df["time_held"])
            .dt.floor(freq="s")
            .astype("string")
        )
        transactions_df["buy_time"] = pd.to_datetime(transactions_df["buy_time"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        transactions_df["sell_time"] = pd.to_datetime(transactions_df["sell_time"]).dt.strftime("%Y-%m-%d %H:%M:%S")

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
                'change_perc': 'Change %',
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

    except Exception as e:
        print(e)
        pass

    with placeholder.container():

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
                    f'<value style="color: {market_perf_color}; text-decoration: none;" target="_blank" href="https://www.binance.com/en/trade/BTCUSDT">'
                    + str(profile_summary.all_time_market_profit)
                    + "</value>"
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
            realised_color = money_color(
                profile_summary.realised_session_profit_incfees_perc
            )

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
                f"<h4 style='text-align: left; margin-left: 30px;'> Bot Performance: <span style='text-align: center; color: {bot_perf_color};'>{round(float(profile_summary.bot_profit_perc),2)}%</span> <span> Est: </span><span style='color: {bot_perf_color}';>${profile_summary.bot_profit} {profile_summary.pair_with}</span></h3>",
                unsafe_allow_html=True,
            )

        with kpi12:
            st.markdown(
                f"<h4 style='text-align: left;  margin-left: 30px; padding-right: 0px'> Completed Trades: {profile_summary.trade_wins + profile_summary.trade_losses} (Wins: <span style='color:green'>{profile_summary.trade_wins}</span>, Losses: <span style='color:red'>{profile_summary.trade_losses} </span>) | Win Ratio: {profile_summary.win_ratio}%</h4>",
                unsafe_allow_html=True,
            )

        with kpi13:
            st.markdown(
                f"<h4 style='text-align: left;  margin-left: 30px; padding-right: 0px'> Strategy: {config['trading_options']['SIGNALLING_MODULES'][0]} SL: {config['trading_options']['STOP_LOSS']}</h4>",
                unsafe_allow_html=True,
            )

        st.markdown("<hr/>", unsafe_allow_html=True)

        st.markdown(
            f"### **_Open Trades_** (Winning: <span style='color:green;'>{open_trades[open_trades['Change %'] > 0].shape[0]}</span> | Losing: <span style='color:red;'>{open_trades[open_trades['Change %'] <= 0].shape[0]}</span>)",
            unsafe_allow_html=True,
        )
        st.dataframe(
            open_trades.style
            .apply(gray_background, axis=0)
            .hide(axis="index")
            .format("{:.2f}%", subset=["Change %", "TP %", "SL %"])
            .applymap(color_negative_values, subset=["Change %", "Profit $"]),
            use_container_width=True
        )
        
        # report_open_trades(open_trades)
        "### **_Closed Trades_**"
        st.dataframe(
            closed_trades.style
            .hide(axis='index')
            .format("{:.2f}%", subset=["Change %", "TP %", "SL %"])
            .apply(gray_background, axis=0)
            .applymap(color_negative_values, subset=["Change %", "Profit $"]),
            use_container_width=True
        )
        
        # report_closed_trades(closed_trades)
        time.sleep(3)