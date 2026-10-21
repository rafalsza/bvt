#!/usr/bin/env python3
"""WaveTrend (LazyBear, same formula as external_strategies/rs_wavetrend.py)
long-only spot strategy with a pre-registered tune -> frozen test protocol.

Events: every wt1-over-wt2 cross-up on bar close. Features per event:
  osmin - min wt1 in the bearish segment that the cross ends
  ema   - close > EMA200
  htf   - higher TF (1h->4h, 4h->1d) last *completed* bar has wt1 > wt2
  div   - bullish divergence vs the previous bearish segment (within
          DIV_LOOKBACK bars): lower price low, higher wt1 low, both oversold
Entry at next bar open. SL = segment low - 0.2%. Exits:
  wtxK  - wt1 crosses below wt2 while wt1 > K -> next bar open
  R<x>  - take profit at x * risk
Max hold MAX_HOLD bars, same-bar SL+TP -> SL, fee 0.1%/side, stop slippage.

Tune: data/1h_until365d (Oct-2023..Oct-2025). Test: data/1h (Oct-2025..Oct-2026).
Selection rule (fixed before looking at the test): highest tune portfolio
net among configs with >= MIN_TUNE_TRADES trades. Success criterion on test:
PF >= 1.15, >= 200 trades, >= 60% positive months, max DD < net profit.

Usage: python wt_backtest.py
"""
import glob
import heapq
import os
from itertools import product

import numpy as np
import pandas as pd

DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TUNE_DIR, TEST_DIR = "1h_until365d", "1h"
FEE = 0.001
STOP_SLIP = 0.0005
SL_BUF = 0.002
TRADE_USDT = 500.0
SLOTS = 5
RISK_RANGE = (0.5, 12.0)   # % distance entry->SL accepted
DIV_LOOKBACK = 60          # bars between the two divergence troughs
MIN_TUNE_TRADES = 150
N1, N2 = 10, 21

TFS = ["1h", "4h"]
OSS = [-50, -60, -75]
FILTERS = ["none", "ema", "htf", "div"]
EXITS = ["wtx0", "wtx40", "R1.5", "R2", "R3"]
HTF_OF = {"1h": "4h", "4h": "1D"}
MAX_HOLD = {"1h": 14 * 24, "4h": 14 * 6}


def load(sub):
    out = {}
    for f in sorted(glob.glob(os.path.join(DATA_ROOT, sub, "*.pkl"))):
        df = pd.read_pickle(f)
        if len(df) >= 500:
            out[os.path.basename(f).split("_")[0]] = df
    return out


def resample(df, tf):
    if tf == "1h":
        return df
    return df.resample(tf, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum"}).dropna()


def wavetrend(h, l, c):
    ap = pd.Series((h + l + c) / 3)
    esa = ap.ewm(span=N1, adjust=False).mean()
    d = (ap - esa).abs().ewm(span=N1, adjust=False).mean()
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.fillna(0).ewm(span=N2, adjust=False).mean()
    wt2 = wt1.rolling(4).mean()
    return wt1.values, wt2.values


def htf_bull(df, tf):
    """bool per bar of `tf` frame: last completed HTF bar has wt1 > wt2."""
    hdf = resample(df, HTF_OF[tf])
    w1, w2 = wavetrend(*(hdf[x].values.astype(float) for x in ("high", "low", "close")))
    bull = w1 > w2
    period = pd.Timedelta(HTF_OF[tf])
    bar_tf = pd.Timedelta(tf)
    frame = resample(df, tf)
    # HTF bar opened at T is complete at T+period; our bar closes at t+bar_tf
    k = np.searchsorted(hdf.index.values,
                        (frame.index + bar_tf - period).values, side="right") - 1
    out = np.zeros(len(frame), dtype=bool)
    ok = k >= 0
    out[ok] = bull[k[ok]]
    return out


def events_for(df, tf):
    f = resample(df, tf)
    o, h, l, c = (f[x].values.astype(float) for x in ("open", "high", "low", "close"))
    w1, w2 = wavetrend(h, l, c)
    ema = pd.Series(c).ewm(span=200, adjust=False).mean().values
    hb = htf_bull(df, tf)
    ev = []
    seg_start = None
    prev_seg = None  # (end_idx, min_wt, min_low)
    for i in range(201, len(c) - 1):
        if np.isnan(w2[i]) or np.isnan(w2[i - 1]):
            continue
        if w1[i] < w2[i] and w1[i - 1] >= w2[i - 1]:
            seg_start = i
        if seg_start is not None and w1[i] > w2[i] and w1[i - 1] <= w2[i - 1]:
            seg = slice(seg_start, i + 1)
            mwt = float(w1[seg].min())
            mlow = float(l[seg].min())
            div = (prev_seg is not None and i - prev_seg[0] <= DIV_LOOKBACK
                   and mlow < prev_seg[2] and mwt > prev_seg[1] and prev_seg[1] < -50)
            ev.append(dict(i=i, osmin=mwt, low=mlow, ema=c[i] > ema[i],
                           htf=bool(hb[i]), div=bool(div)))
            prev_seg = (i, mwt, mlow)
            seg_start = None
    return f.index, (o, h, l, c, w1, w2), ev


def sim(arr, e, exit_mode, max_hold):
    o, h, l, c, w1, w2 = arr
    j = e["i"] + 1
    entry = o[j]
    sl = e["low"] * (1 - SL_BUF)
    if entry <= sl:
        return None
    risk = entry - sl
    rp = risk / entry * 100
    if not RISK_RANGE[0] <= rp <= RISK_RANGE[1]:
        return None
    tp = entry + float(exit_mode[1:]) * risk if exit_mode[0] == "R" else None
    wtk = float(exit_mode[3:]) if exit_mode.startswith("wtx") else None
    n = len(c)
    for k in range(j, min(n, j + max_hold)):
        if l[k] <= sl:
            return j, k, min(o[k], sl) / entry - 1 - 2 * FEE - STOP_SLIP
        if tp is not None and h[k] >= tp:
            return j, k, max(o[k], tp) / entry - 1 - 2 * FEE
        if wtk is not None and k + 1 < n and w1[k] < w2[k] and w1[k - 1] >= w2[k - 1] \
                and w1[k] > wtk:
            return j, k + 1, o[k + 1] / entry - 1 - 2 * FEE
    k = min(n - 1, j + max_hold)
    return j, k, c[k] / entry - 1 - 2 * FEE


def run(data):
    """-> DataFrame of trades for every (tf, exit) with event features."""
    rows = []
    for tf in TFS:
        for sym, df in data.items():
            idx, arr, evs = events_for(df, tf)
            for e in evs:
                for ex in EXITS:
                    t = sim(arr, e, ex, MAX_HOLD[tf])
                    if t is None:
                        continue
                    j, k, r = t
                    rows.append((tf, ex, e["osmin"], e["ema"], e["htf"], e["div"],
                                 idx[j], idx[k], sym, r))
    return pd.DataFrame(rows, columns=["tf", "ex", "osmin", "ema", "htf", "div",
                                       "et", "xt", "sym", "ret"])


def select(df, tf, os_, flt, ex):
    m = (df.tf == tf) & (df.ex == ex) & (df.osmin <= os_)
    if flt != "none":
        m &= df[flt]
    return df[m]


def portfolio(g):
    rows = sorted(zip(g.et, g.xt, g.sym, g.ret))
    heap, open_syms, taken = [], set(), []
    for et, xt, sym, r in rows:
        while heap and heap[0][0] <= et:
            open_syms.discard(heapq.heappop(heap)[1])
        if len(heap) >= SLOTS or sym in open_syms:
            continue
        heapq.heappush(heap, (xt, sym))
        open_syms.add(sym)
        taken.append((et, xt, r))
    return pd.DataFrame(taken, columns=["et", "xt", "ret"])


def summary(tk):
    if tk.empty:
        return dict(n=0, wr=0, net=0, pf=0, pos=0, months=0, dd=0)
    r = tk.ret.values
    gl = -r[r < 0].sum()
    monthly = tk.groupby(tk.et.dt.strftime("%Y-%m")).ret.sum() * TRADE_USDT
    eq = (tk.sort_values("xt").ret * TRADE_USDT).cumsum()
    return dict(n=len(r), wr=(r > 0).mean() * 100, net=r.sum() * TRADE_USDT,
                pf=r[r > 0].sum() / gl if gl else 99.0, pos=int((monthly > 0).sum()),
                months=len(monthly), dd=float((eq.cummax() - eq).max()),
                monthly=monthly)


def fmt(s):
    return (f"n={s['n']:4d} wr={s['wr']:5.1f}% net=${s['net']:7.0f} PF={s['pf']:.2f} "
            f"months+={s['pos']}/{s['months']} DD=${s['dd']:.0f}")


# Pre-registered (2026-10-21, before downloading Oct-2022..Oct-2023 data):
# primary config and the whole 4h + daily-WT family; PASS needs primary
# PF >= 1.15 and median family PF > 1.15.
HOLDOUT_PRIMARY = ("4h", -50, "htf", "R2")
HOLDOUT_FAMILY = [("4h", o, "htf", e) for o in (-50, -60) for e in EXITS]


def run_holdout(sub):
    data = load(sub)
    print(f"HOLDOUT {sub}: {len(data)} symbols", flush=True)
    x = run(data)
    pfs = []
    for cfg in HOLDOUT_FAMILY:
        s = summary(portfolio(select(x, *cfg)))
        pfs.append(s["pf"])
        mark = "  <- primary" if cfg == HOLDOUT_PRIMARY else ""
        print(f"{str(cfg):32s} {fmt(s)}{mark}")
    p = summary(portfolio(select(x, *HOLDOUT_PRIMARY)))
    if p["n"]:
        print("primary monthly $: " + " ".join(
            f"{k[2:]}:{int(v):+d}" for k, v in p["monthly"].items()))
    med = float(np.median(pfs))
    ok = p["pf"] >= 1.15 and med > 1.15
    print(f"\nprimary PF={p['pf']:.2f}, family median PF={med:.2f} -> "
          f"{'PASS' if ok else 'FAIL'}")


def main():
    import sys
    if "--holdout" in sys.argv:
        run_holdout(sys.argv[sys.argv.index("--holdout") + 1])
        return
    tune = load(TUNE_DIR)
    print(f"TUNE {TUNE_DIR}: {len(tune)} symbols", flush=True)
    tdf = run(tune)
    res = []
    for tf, os_, flt, ex in product(TFS, OSS, FILTERS, EXITS):
        s = summary(portfolio(select(tdf, tf, os_, flt, ex)))
        res.append(((tf, os_, flt, ex), s))
    res.sort(key=lambda x: -x[1]["net"])
    print("\n=== TUNE: top 15 configs (portfolio 5 slots x $500) ===")
    for cfg, s in res[:15]:
        print(f"{str(cfg):32s} {fmt(s)}")
    prof = sum(1 for _, s in res if s["net"] > 0)
    print(f"profitable on tune: {prof}/{len(res)}")

    eligible = [x for x in res if x[1]["n"] >= MIN_TUNE_TRADES]
    frozen, fs = eligible[0]
    print(f"\nFROZEN (selection rule): {frozen}  tune: {fmt(fs)}")

    test = load(TEST_DIR)
    print(f"\nTEST {TEST_DIR}: {len(test)} symbols", flush=True)
    xdf = run(test)
    s = summary(portfolio(select(xdf, *frozen)))
    print(f"TEST frozen {frozen}: {fmt(s)}")
    print("monthly $: " + " ".join(f"{k[2:]}:{int(v):+d}" for k, v in s["monthly"].items()))
    ok = (s["pf"] >= 1.15 and s["n"] >= 200 and s["pos"] >= 0.6 * s["months"]
          and s["dd"] < s["net"])
    print(f"\nCRITERION (PF>=1.15, n>=200, >=60% months+, DD<net): "
          f"{'PASS' if ok else 'FAIL'}")

    # robustness context only (not used for selection): top-10 tune configs on test
    print("\n--- context: top-10 tune configs on test ---")
    for cfg, ts in eligible[:10]:
        print(f"{str(cfg):32s} {fmt(summary(portfolio(select(xdf, *cfg))))}")


if __name__ == "__main__":
    main()
