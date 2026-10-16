"""Per-symbol comparison dashboard for the pump-detector strategy."""

import os
import warnings

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import simulate_faithful as sf

warnings.filterwarnings("ignore")
REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "1m_binance")


def main(top_n=10):
    frames = sf.load_frames(DATA)
    all_trades = []
    for sym, df in frames.items():
        all_trades.extend(sf.simulate_symbol(sym, df))
    trades = pd.DataFrame(all_trades).sort_values("entry_time")
    trades, _ = sf.apply_portfolio_constraints(trades)

    g = trades.groupby("symbol")
    stats = pd.DataFrame({
        "pnl": g["pnl"].sum().round(2),
        "trades": g["pnl"].count(),
        "wr": g.apply(lambda x: (x["pnl"] > 0).mean() * 100).round(1),
        "avg": g["pnl"].mean().round(3),
        "best": g["pnl"].max().round(2),
        "worst": g["pnl"].min().round(2),
    }).sort_values("pnl", ascending=False)

    top = stats.head(top_n)
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=["Total PnL (USDT)", "Trades", "Win rate %", "Avg PnL / trade"],
        specs=[[{"type": "bar"}, {"type": "bar"}],
               [{"type": "bar"}, {"type": "bar"}]],
    )
    syms = top.index.tolist()
    colors = ["lime" if v > 0 else "red" for v in top["pnl"]]
    fig.add_bar(x=syms, y=top["pnl"], marker_color=colors, name="PnL", row=1, col=1)
    fig.add_bar(x=syms, y=top["trades"], name="trades", row=1, col=2)
    fig.add_bar(x=syms, y=top["wr"], name="WR%", row=2, col=1)
    fig.add_bar(x=syms, y=top["avg"], name="avg PnL", row=2, col=2)
    fig.update_layout(template="plotly_dark", showlegend=False,
                      title=f"Pump-detector — top {top_n} symbols (1y)",
                      autosize=True, width=None, height=None)

    os.makedirs(REPORT_DIR, exist_ok=True)
    fig.write_html(os.path.join(REPORT_DIR, "PUMP_compare.html"),
                   default_width="100%", default_height="100%")
    print(top.to_string())
    print(f"\nsaved -> report/PUMP_compare.html")


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
