"""Backtest of the rs_buy_dip external strategy (4-stage filter).

Replicates the live pipeline on yearly 1m data resampled per timeframe:

  Stage1 (1h):  WT1 < -75 AND close < EMA200 AND close < lin_reg_lower
                AND CMO14 < -50
  Stage2 (15m): close < lin_reg_lower
  Stage3 (5m):  WT1 < -60
  Stage4 (1m):  CMO14 < -50 AND WT1 < -60

Indicators copied verbatim from external_strategies/technical_indicators.py
(EMA recursion, CMO sums, WaveTrend, regression channel over the last
500 candles of each timeframe — same as the live 500-candle fetch).

Exits use the same SL/TP/trailing engine as simulate_faithful.py.
"""

import glob
import importlib.util
import os
import pickle
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Exit parameters (mirror config)
STOP_LOSS = 5.0
TAKE_PROFIT = 5.0
TRAILING_TAKE_PROFIT = 1.0
TRAILING_STOP_LOSS = 2.0
TRADING_FEE = 0.1
TRADE_TOTAL = 50.0
TRADE_SLOTS = 8
INIT_CASH = TRADE_TOTAL * TRADE_SLOTS

# Signal thresholds (SignalConfig)
WT_OVERSOLD = -75
CMO_OVERSOLD = -50
WT_MOMENTUM = -60
REG_WINDOW = 500  # live fetches 500 candles per call


def _load_wavetrend_params():
    spec = importlib.util.spec_from_file_location(
        "w_params",
        os.path.join(
            REPO_ROOT,
            "bitget_volatility_trading_bot",
            "external_strategies",
            "w_params.py",
        ),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.wavetrend_parameters


WAVETREND_PARAMS = _load_wavetrend_params()


# ---- indicators (verbatim logic from technical_indicators.py) ----

def ema(data, period):
    alpha = 2.0 / (period + 1.0)
    out = np.zeros_like(data, dtype=float)
    out[0] = data[0]
    for i in range(1, len(data)):
        out[i] = alpha * data[i] + (1 - alpha) * out[i - 1]
    return out


def cmo(data, period=14):
    changes = np.diff(data)
    gains = np.where(changes > 0, changes, 0.0)
    losses = np.where(changes < 0, -changes, 0.0)
    out = np.full(len(data), np.nan)
    for i in range(period, len(data)):
        sg = gains[i - period : i].sum()
        sl = losses[i - period : i].sum()
        out[i] = 100 * (sg - sl) / (sg + sl) if (sg + sl) != 0 else 0
    return out


def wavetrend(high, low, close, n1, n2):
    ap = (high + low + close) / 3.0
    esa = ema(ap, n1)
    d = ema(np.abs(ap - esa), n1)
    d = np.where((d == 0) | np.isnan(d), 1e-10, d)
    ci = (ap - esa) / (0.015 * d)
    return ema(ci, n2)


def regression_lower(close):
    """lower band = lin_reg - 2*std(residuals), over the array given."""
    y = np.asarray(close, dtype=float)
    X = np.arange(len(y))
    slope, intercept = np.polyfit(X, y, 1)
    lr = intercept + slope * X
    std = np.std(y - lr)
    return lr - 2 * std


def resample(df_1m, rule):
    return (
        df_1m.resample(rule)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last",
              "volume": "sum"})
        .dropna()
    )


def rolling_lower_band(close, window):
    """Regression-lower for each bar using the trailing `window` bars."""
    n = len(close)
    out = np.full(n, np.nan)
    X = np.arange(window)
    # precompute polyfit via vectorized formulas
    sx = X.sum(); sxx = (X * X).sum()
    for i in range(window - 1, n):
        y = close[i - window + 1 : i + 1]
        sy = y.sum(); sxy = (X * y).sum()
        slope = (window * sxy - sx * sy) / (window * sxx - sx * sx)
        intercept = (sy - slope * sx) / window
        resid = y - (intercept + slope * X)
        out[i] = intercept + slope * (window - 1) - 2 * np.std(resid)
    return out


def simulate_exit(df_1m, entry_idx):
    """Replay exit engine on 1m candles starting at entry bar index."""
    e = df_1m["close"].iloc[entry_idx]
    peak = df_1m["high"].iloc[entry_idx]
    armed = (peak / e - 1) * 100 >= TRAILING_TAKE_PROFIT
    for j in range(entry_idx + 1, len(df_1m)):
        peak = max(peak, df_1m["high"].iloc[j])
        if (peak / e - 1) * 100 >= TRAILING_TAKE_PROFIT:
            armed = True
        sl = e * (1 - STOP_LOSS / 100)
        if armed:
            sl = max(sl, peak * (1 - TRAILING_STOP_LOSS / 100))
        tp = e * (1 + TAKE_PROFIT / 100)
        lo, hi = df_1m["low"].iloc[j], df_1m["high"].iloc[j]
        exit_price = reason = None
        if lo <= sl:
            exit_price = sl
            reason = "trailing_sl" if armed and sl > e * (1 - STOP_LOSS / 100) else "sl"
        elif hi >= tp:
            exit_price, reason = tp, "tp"
        if exit_price is not None:
            ret = exit_price / e - 1
            return e, exit_price, ret * 100, TRADE_TOTAL * ret - TRADE_TOTAL * (TRADING_FEE / 100) * 2, reason, j
    return None


def analyze_symbol(sym, df_1m):
    """Full 4-stage pipeline -> list of trades."""
    n1, n2 = WAVETREND_PARAMS.get(sym, (10, 21))

    h1 = resample(df_1m, "1h")
    m15 = resample(df_1m, "15min")
    m5 = resample(df_1m, "5min")

    h1_close = h1["close"].values
    h1_wt1 = wavetrend(h1["high"].values, h1["low"].values, h1_close, n1, n2)
    h1_ema200 = ema(h1_close, 200)
    h1_cmo = cmo(h1_close, 14)
    h1_lower = rolling_lower_band(h1_close, REG_WINDOW)

    m15_close = m15["close"].values
    m15_lower = rolling_lower_band(m15_close, REG_WINDOW)

    m5_wt1 = wavetrend(m5["high"].values, m5["low"].values, m5["close"].values, n1, n2)

    m1_cmo = cmo(df_1m["close"].values, 14)
    m1_wt1 = wavetrend(df_1m["high"].values, df_1m["low"].values,
                       df_1m["close"].values, n1, n2)

    # index lookup: 15m/5m bar that CLOSES at the 1h bar close
    m15_idx = m15.index
    m5_idx = m5.index
    m1_idx = df_1m.index

    trades = []
    stats = {"s1": 0, "s2": 0, "s3": 0, "s4": 0}
    for i in range(len(h1)):
        if not (h1_wt1[i] < WT_OVERSOLD and h1_close[i] < h1_ema200[i]
                and h1_close[i] < h1_lower[i] and h1_cmo[i] < CMO_OVERSOLD):
            continue
        stats["s1"] += 1
        t = h1.index[i]

        # stage2: last closed 15m bar at/before t
        k = m15_idx.searchsorted(t, side="right") - 1
        if k < 0 or not (m15_close[k] < m15_lower[k]):
            continue
        stats["s2"] += 1

        # stage3: last closed 5m bar at/before t
        k5 = m5_idx.searchsorted(t, side="right") - 1
        if k5 < 0 or not (m5_wt1[k5] < WT_MOMENTUM):
            continue
        stats["s3"] += 1

        # stage4: 1m bar ending at t
        k1 = m1_idx.searchsorted(t, side="right") - 1
        if k1 < 0 or not (m1_cmo[k1] < CMO_OVERSOLD and m1_wt1[k1] < WT_MOMENTUM):
            continue
        stats["s4"] += 1

        res = simulate_exit(df_1m, k1)
        if res:
            e, xp, ret, pnl, reason, j = res
            trades.append({
                "symbol": sym, "entry_time": df_1m.index[k1],
                "exit_time": df_1m.index[j], "entry": e, "exit": xp,
                "ret_pct": ret, "pnl": pnl, "reason": reason,
            })
    return trades, stats


def main():
    frames = {}
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "1m_binance", "*.pkl"))):
        sym = os.path.basename(f).split("_")[0]
        frames[sym] = pd.read_pickle(f)
    print(f"{len(frames)} symbols")

    all_trades = []
    funnel = {"s1": 0, "s2": 0, "s3": 0, "s4": 0}
    for sym, df in frames.items():
        trades, stats = analyze_symbol(sym, df)
        for k in funnel:
            funnel[k] += stats[k]
        all_trades.extend(trades)
        if stats["s1"]:
            print(f"  {sym}: stage1={stats['s1']} -> trades={len(trades)}", flush=True)

    print(f"\nFunnel: 1h={funnel['s1']} -> 15m={funnel['s2']} "
          f"-> 5m={funnel['s3']} -> 1m={funnel['s4']}")

    if not all_trades:
        print("No rs_buy_dip trades in the whole year.")
        return

    trades = pd.DataFrame(all_trades).sort_values("entry_time")
    import simulate_faithful as sf
    trades, _ = sf.apply_portfolio_constraints(trades)

    wins = trades[trades.pnl > 0]
    losses = trades[trades.pnl <= 0]
    print(f"\n{'='*60}\nrs_buy_dip backtest (1 year, {len(frames)} majors)\n{'='*60}")
    print(f"Trades             : {len(trades)}")
    print(f"Total PnL          : {trades.pnl.sum():+.2f} USDT ({trades.pnl.sum()/INIT_CASH*100:+.1f}%)")
    print(f"Win rate           : {len(wins)/len(trades)*100:.1f}%")
    print(f"Avg trade          : {trades.pnl.mean():.3f} USDT")
    print(f"Best / worst       : {trades.pnl.max():.2f} / {trades.pnl.min():.2f}")
    if len(losses) and losses.pnl.sum() != 0:
        print(f"Profit factor      : {wins.pnl.sum()/abs(losses.pnl.sum()):.2f}")
    trades["month"] = pd.to_datetime(trades["entry_time"]).dt.to_period("M")
    print("\nPnL per month:")
    print(trades.groupby("month")["pnl"].agg(["sum", "count"]).round(2).to_string())
    print("\nExit reasons:")
    print(trades["reason"].value_counts().to_string())


if __name__ == "__main__":
    main()
