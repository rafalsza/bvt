"""Exact replica of wavetrend-single coin.py on our yearly data.

Same IndicatorFactory, same methods (trend_below/ema_above = LEVEL
comparisons), same exits and SL — only the data source and params differ.
"""

import os
import sys
import warnings

import numpy as np
import pandas as pd
import vectorbt as vbt
from vectorbt.portfolio.enums import SizeType

import rs_buy_dip_backtest as rb

warnings.filterwarnings("ignore")


def wavetrend(high, low, close, n1, n2, os_, ob):
    ap = (high + low + close) / 3.0
    ap = pd.DataFrame(ap)
    esa = ap.ewm(span=n1, adjust=False).mean()
    d = (abs(ap - esa)).ewm(span=n1, adjust=False).mean()
    ci = (ap - esa) / (0.015 * d)
    wt1 = ci.ewm(span=n2, adjust=False).mean()
    wt2 = wt1.rolling(4).mean()
    trend = np.where(wt1 < os_, -1, 0)
    trend = np.where(wt1 > ob, 1, trend)
    return wt1, wt2, trend


def main(sym="BTCUSDT", n1=10, n2=21, os_=-75, ob=60):
    df_1m = pd.read_pickle(f"data/1m_binance/{sym}_13m.pkl")
    df = rb.resample(df_1m, "1h")
    high, low, close = df["high"], df["low"], df["close"]

    Wavetrend = vbt.IndicatorFactory(
        class_name="Wavetrend", short_name="wt",
        input_names=["high", "low", "close"],
        param_names=["n1", "n2", "os", "ob"],
        output_names=["wt1", "wt2", "trend"],
    ).from_apply_func(wavetrend)

    wt = Wavetrend.run(high, low, close, n1, n2, os_, ob)
    ema_200 = pd.Series(rb.ema(close.values, 200), index=close.index)

    # level semantics identical to the original test:
    # trend_below(0)  -> trend < 0        (wt1 < os)
    # ema_above(close)-> ema200 > close   (price below EMA200)
    entries = (wt.trend < 0) & (ema_200 > close)
    exits = wt.trend > 0

    print(f"entry signals: {int(entries.sum())} | exit signals: {int(exits.sum())}")

    pf = vbt.Portfolio.from_signals(
        close=close, entries=entries, exits=exits,
        size_type=SizeType.Value, size=1000, sl_stop=0.1,
        fees=0.075 / 100, freq="1h", init_cash="auto",
    )
    st = pf.stats()
    print(f"return {st['Total Return [%]']:.2f}% | trades {pf.trades.count()} "
          f"| WR {st.get('Win Rate [%]', float('nan')):.1f}% "
          f"| PF {st.get('Profit Factor', float('nan')):.2f} "
          f"| MaxDD {st['Max Drawdown [%]']:.1f}%")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    n1 = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    n2 = int(sys.argv[3]) if len(sys.argv) > 3 else 21
    main(sym, n1, n2)
