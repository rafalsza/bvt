"""Generate interactive vectorbt reports (Plotly HTML) for local viewing.

Usage: python report_vbt.py [SYMBOL] [timeframe]
Serves files via `python -m http.server` from backtest/report/.
"""

import glob
import os
import sys
import warnings

import numpy as np
import pandas as pd
import vectorbt as vbt

import rs_buy_dip_backtest as rb

warnings.filterwarnings("ignore")
REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "1m_binance")

TRADE_SIZE, FEE, INIT_CASH = 50.0, 0.001, 400.0


def build(sym: str, tf: str):
    df_1m = pd.read_pickle(os.path.join(DATA_DIR, f"{sym}_13m.pkl"))
    if tf != "1m":
        df = rb.resample(df_1m, tf)
    else:
        df = df_1m
    print(f"{sym} {tf}: {len(df)} bars, {df.index[0]} -> {df.index[-1]}")

    close, high, low = df["close"], df["high"], df["low"]
    # w_params values are tuned for lower timeframes and too smooth on 1h;
    # use standard (10,21) unless a pair is passed on the CLI
    n1, n2 = 10, 21
    if len(sys.argv) > 3:
        n1, n2 = map(int, sys.argv[3].split(","))
    wt1 = pd.Series(
        rb.wavetrend(high.values, low.values, close.values, n1, n2), index=df.index
    )
    e200 = pd.Series(rb.ema(close.values, 200), index=df.index)

    # Strategy from wavetrend-single coin.py:
    # trend: -1 wt1<-75, +1 wt1>60, else 0
    # entries = trend crosses below 0 AND close < EMA200
    # exits   = trend crosses above 0  (+ sl_stop 10%)
    trend = pd.Series(
        np.where(wt1 < -75, -1, np.where(wt1 > 60, 1, 0)), index=df.index
    )
    entries = (trend.shift(1) >= 0) & (trend < 0) & (close < e200)
    exits = (trend.shift(1) <= 0) & (trend > 0)

    pf = vbt.Portfolio.from_signals(
        close=close,
        open=close,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        price=close,
        sl_stop=0.10,
        fees=FEE,
        init_cash=INIT_CASH,
        size=TRADE_SIZE,
        size_type="value",
        cash_sharing=True,
        freq=tf,
    )

    os.makedirs(REPORT_DIR, exist_ok=True)
    stats = pf.stats()
    print(stats[["Total Return [%]", "Total Trades", "Win Rate [%]", "Profit Factor", "Max Drawdown [%]"]].to_string())

    tag = f"{sym}_{tf}_n{n1}_{n2}"
    html_kw = dict(default_width="100%", default_height="100%")
    fig = pf.plot(title=f"{sym} | WT({n1},{n2}) dip-cross + EMA200 | SL-10% + WT>+60 exit")
    fig.update_layout(autosize=True, width=None, height=None)
    fig.write_html(os.path.join(REPORT_DIR, f"{tag}_portfolio.html"), **html_kw)

    tfig = pf.trades.plot(title=f"{sym} | Trades")
    tfig.update_layout(autosize=True, width=None, height=None)
    tfig.write_html(os.path.join(REPORT_DIR, f"{tag}_trades.html"), **html_kw)

    # price + wt1 + entry/exit markers for context
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    ctx = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.65, 0.35],
                        subplot_titles=[f"{sym} price + signals", "WaveTrend (wt1)"])
    ctx.add_trace(go.Candlestick(x=df.index, open=df["open"], high=high,
                                 low=low, close=close, name=sym), row=1, col=1)
    ctx.add_trace(go.Scatter(x=df.index, y=e200, name="EMA200",
                             line=dict(color="orange", width=1)), row=1, col=1)
    ent_idx = df.index[entries.values]
    ctx.add_trace(go.Scatter(x=ent_idx, y=low[ent_idx]*0.99, mode="markers",
                             marker=dict(symbol="triangle-up", size=9, color="lime"),
                             name="entry"), row=1, col=1)
    # all oversold bars (incl. skipped while in position)
    os_bars = df.index[(wt1 < -75).values & (close < e200).values]
    ctx.add_trace(go.Scatter(x=os_bars, y=low[os_bars]*0.985, mode="markers",
                             marker=dict(symbol="circle", size=5, color="magenta",
                                         opacity=0.6),
                             name="wt1<-75 & <EMA200 (all bars)"), row=1, col=1)
    ctx.add_trace(go.Scatter(x=df.index, y=wt1, name="wt1",
                             line=dict(color="cyan", width=1)), row=2, col=1)
    for lvl, c in [(60, "red"), (-75, "green"), (0, "gray")]:
        ctx.add_hline(y=lvl, line=dict(color=c, dash="dash", width=0.7), row=2, col=1)
    ctx.update_layout(template="plotly_dark", autosize=True, height=None)
    ctx.write_html(os.path.join(REPORT_DIR, f"{tag}_chart.html"), **html_kw)
    print(f"Saved reports to {REPORT_DIR}")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    tf = sys.argv[2] if len(sys.argv) > 2 else "1h"
    build(sym, tf)
