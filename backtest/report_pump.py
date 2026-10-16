"""Report for the original BVT pump-detector strategy.

Faithful simulation trades -> portfolio equity curve + per-symbol
candlestick chart with entry/exit markers.
"""

import os
import pickle
import sys
import warnings

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import simulate_faithful as sf

warnings.filterwarnings("ignore")
REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report")
BINANCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "1m_binance")


def main():
    frames = sf.load_frames(BINANCE_DIR)
    all_trades = []
    for sym, df in frames.items():
        all_trades.extend(sf.simulate_symbol(sym, df))
    trades = pd.DataFrame(all_trades).sort_values("entry_time")
    trades, _ = sf.apply_portfolio_constraints(trades)
    os.makedirs(REPORT_DIR, exist_ok=True)

    # --- equity curve: replay trades in time order ---
    cash, curve, t_idx = sf.INIT_CASH, [], []
    for _, t in trades.iterrows():
        cash += t["pnl"]
        curve.append(cash)
        t_idx.append(t["exit_time"])
    fig = go.Figure(go.Scatter(x=t_idx, y=curve, mode="lines",
                               line=dict(color="cyan", width=1.5)))
    fig.update_layout(template="plotly_dark", title="BVT pump-detector — equity curve (1y, 20 majors, 400 USDT start)",
                      autosize=True, width=None, height=None,
                      xaxis_title="date", yaxis_title="equity (USDT)")
    fig.write_html(os.path.join(REPORT_DIR, "PUMP_equity.html"),
                   default_width="100%", default_height="100%")

    # --- per-symbol chart ---
    sym = sys.argv[1] if len(sys.argv) > 1 else "FILUSDT"
    df = frames[sym]
    st = trades[trades.symbol == sym]
    ctx = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.7, 0.3],
                        subplot_titles=[f"{sym} — pump-detector trades ({len(st)})",
                                        "1m % change"])
    ctx.add_trace(go.Candlestick(x=df.index, open=df["open"], high=df["high"],
                                 low=df["low"], close=df["close"], name=sym),
                  row=1, col=1)
    chg = df["close"].pct_change() * 100
    ctx.add_trace(go.Scatter(x=df.index, y=chg, name="1m chg %",
                             line=dict(width=0.6, color="gray")), row=2, col=1)
    ctx.add_hline(y=sf.CHANGE_IN_PRICE, line=dict(color="red", dash="dash"),
                  row=2, col=1)
    for _, t in st.iterrows():
        et = pd.Timestamp(t["entry_time"])
        xt = pd.Timestamp(t["exit_time"])
        et = et.tz_localize("UTC") if et.tzinfo is None else et.tz_convert("UTC")
        xt = xt.tz_localize("UTC") if xt.tzinfo is None else xt.tz_convert("UTC")
        epos = df.index.searchsorted(et)
        xpos = df.index.searchsorted(xt)
        if epos < len(df):
            ctx.add_trace(go.Scatter(x=[df.index[epos]], y=[df["low"].iloc[epos]*0.99],
                                     mode="markers", showlegend=False,
                                     marker=dict(symbol="triangle-up", size=10,
                                                 color="lime")), row=1, col=1)
        if xpos < len(df):
            ctx.add_trace(go.Scatter(x=[df.index[xpos]], y=[df["high"].iloc[xpos]*1.01],
                                     mode="markers", showlegend=False,
                                     marker=dict(symbol="triangle-down", size=10,
                                                 color="red" if t["pnl"] <= 0 else "orange")),
                          row=1, col=1)
    ctx.update_layout(template="plotly_dark", autosize=True, width=None, height=None)
    ctx.write_html(os.path.join(REPORT_DIR, f"PUMP_{sym}.html"),
                   default_width="100%", default_height="100%")
    print(f"trades plotted for {sym}: {len(st)} | total PnL all syms: {trades.pnl.sum():+.2f}")


if __name__ == "__main__":
    main()
