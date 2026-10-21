#!/usr/bin/env python3
"""Bullish order-block retest strategy, OB definition from
joshyattridge/smart-money-concepts (smc.swing_highs_lows + smc.ob),
re-implemented causally:

- swing high/low at k (library window: [k-L+1, k+L]) is only known at bar
  k+L; consecutive same-type swings keep the more extreme one (library
  cleanup), applied as swings get confirmed.
- bullish OB is created at bar i when close[i] breaks the last confirmed,
  not-yet-crossed swing high s; OB candle = last lowest-low candle in
  (s, i) (default i-1). Top/Bottom = that candle's high/low. OBVolume and
  Percentage exactly as the library (v[i]+v[i-1] vs v[i-2]).
- OB dies once low < Bottom (library mitigation / breaker).

Trade (spot long): limit buy at OB Top on first retest within MAX_WAIT
bars, SL below Bottom, TP at R multiples. Same-bar SL+TP -> SL.

Usage: python ob_backtest.py [timeframe]
"""
import glob
import heapq
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FEE = 0.001            # per side
STOP_SLIP = 0.0005     # extra slippage on stop exits
TRADE_USDT = 500.0
SL_BUF = 0.002         # SL this far under OB bottom
IS_FRAC = 2 / 3        # first 2/3 of time = in-sample


def load(tf):
    data = {}
    for f in sorted(glob.glob(os.path.join(DATA_ROOT, tf, "*.pkl"))):
        df = pd.read_pickle(f)
        if len(df) < 500:
            continue
        sym = os.path.basename(f).split("_")[0]
        data[sym] = df
    return data


def confirmed_swings(h, l, L):
    """Return list of (confirm_idx, swing_idx, type) in confirm order,
    with library-style consecutive-swing cleanup applied causally.
    Output events: ('set', idx, type) meaning 'last swing of type is idx'."""
    n = len(h)
    hi_max = pd.Series(h).rolling(2 * L).max().shift(-L).values
    lo_min = pd.Series(l).rolling(2 * L).min().shift(-L).values
    last_high = np.full(n, -1, dtype=np.int64)  # last confirmed swing high at bar i
    last_low = np.full(n, -1, dtype=np.int64)
    cur_high = -1
    cur_low = -1
    prev_type = 0
    prev_idx = -1
    for i in range(n):
        k = i - L
        if k >= L:
            t = 0
            if h[k] == hi_max[k]:
                t = 1
            elif l[k] == lo_min[k]:
                t = -1
            if t == 1:
                if prev_type == 1:
                    if h[k] > h[prev_idx]:
                        cur_high = k
                        prev_idx = k
                else:
                    cur_high = k
                    prev_type, prev_idx = 1, k
            elif t == -1:
                if prev_type == -1:
                    if l[k] < l[prev_idx]:
                        cur_low = k
                        prev_idx = k
                else:
                    cur_low = k
                    prev_type, prev_idx = -1, k
        last_high[i] = cur_high
        last_low[i] = cur_low
    return last_high, last_low


def htf_structure(df, L=5):
    """Per completed 4h bar: +1 if the last structure break (close beyond
    the last confirmed swing) was bullish, -1 if bearish, 0 unknown.
    Returns (bar_open_times, state)."""
    d4 = df.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    h, l, c = (d4[x].values.astype(float) for x in ("high", "low", "close"))
    lh, ll = confirmed_swings(h, l, L)
    state = np.zeros(len(c), dtype=np.int8)
    st, crossed_h, crossed_l = 0, set(), set()
    for i in range(len(c)):
        s = lh[i]
        if s >= 0 and s not in crossed_h and c[i] > h[s]:
            crossed_h.add(s)
            st = 1
        s = ll[i]
        if s >= 0 and s not in crossed_l and c[i] < l[s]:
            crossed_l.add(s)
            st = -1
        state[i] = st
    return d4.index.values, state


def find_obs(df, L):
    o, h, l, c, v = (df[x].values.astype(float) for x in ("open", "high", "low", "close", "volume"))
    last_high, _ = confirmed_swings(h, l, L)
    crossed = set()
    vavg = pd.Series(v).rolling(50, min_periods=10).mean().values
    ema = pd.Series(c).ewm(span=200, adjust=False).mean().values
    # library smc.fvg bullish: high[m-1] < low[m+1] and candle m bullish;
    # stored at m+1 (the bar where it becomes known)
    fvg_known = np.zeros(len(c), dtype=bool)
    fvg_known[2:] = (h[:-2] < l[2:]) & (c[1:-1] > o[1:-1])
    fvg_cum = np.concatenate([[0], np.cumsum(fvg_known)])
    htf = np.zeros(len(c), dtype=np.int8)
    if isinstance(df.index, pd.DatetimeIndex):
        t4, st4 = htf_structure(df)
        bar = df.index.values
        k = np.searchsorted(t4, bar - np.timedelta64(3, "h"), side="right") - 1
        ok = k >= 0
        htf[ok] = st4[k[ok]]
    obs = []
    for i in range(2, len(c)):
        s = last_high[i]
        if s < 0 or s in crossed or c[i] <= h[s]:
            continue
        crossed.add(s)
        ob_i = i - 1
        if i - s > 1:
            seg = l[s + 1:i]
            ob_i = s + 1 + int(np.flatnonzero(seg == seg.min())[-1])
        top, bot = h[ob_i], l[ob_i]
        hv, lv = v[i] + v[i - 1], v[i - 2]
        mx = max(hv, lv)
        pct = min(hv, lv) / mx * 100 if mx else 100.0
        volr = (v[i] + v[i - 1] + v[i - 2]) / (3 * vavg[i]) if vavg[i] > 0 else 0.0
        obs.append(dict(i=i, top=top, bot=bot, pct=pct, volr=volr,
                        trend=c[i] > ema[i], disp=(c[i] - top) / top * 100,
                        # FVG center m in (ob_i, i) -> known at m+1 in [ob_i+2, i]
                        fvg=fvg_cum[i + 1] - fvg_cum[ob_i + 2] > 0,
                        htf=htf[i] == 1))
    return obs, (o, h, l, c)


def sim_trade(ob, ohlc, R, max_wait, max_hold):
    o, h, l, c = ohlc
    top, bot = ob["top"], ob["bot"]
    sl = bot * (1 - SL_BUF)
    n = len(c)
    for j in range(ob["i"] + 1, min(n, ob["i"] + 1 + max_wait)):
        if l[j] < bot and o[j] < bot:
            return None  # gapped through the zone -> mitigated, no fill
        if l[j] <= top:
            entry = min(o[j], top)
            risk = entry - sl
            if risk <= 0:
                return None
            tp = entry + R * risk
            if l[j] <= sl:
                return j, j, sl / entry - 1 - 2 * FEE - STOP_SLIP, risk / entry
            for k in range(j + 1, min(n, j + 1 + max_hold)):
                if l[k] <= sl:
                    px = min(o[k], sl)
                    return j, k, px / entry - 1 - 2 * FEE - STOP_SLIP, risk / entry
                if h[k] >= tp:
                    px = max(o[k], tp)
                    return j, k, px / entry - 1 - 2 * FEE, risk / entry
            k = min(n - 1, j + max_hold)
            return j, k, c[k] / entry - 1 - 2 * FEE, risk / entry
    return None


def stats(rets):
    if not rets:
        return 0, 0.0, 0.0, 0.0
    r = np.array(rets)
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    return len(r), (r > 0).mean() * 100, r.sum() * TRADE_USDT, gw / gl if gl else 99.0


def portfolio(trades, slots=5):
    """trades: list of (entry_ts, exit_ts, sym, ret). Slot-limited, one per symbol."""
    trades = sorted(trades)
    open_h, open_syms, taken = [], {}, []
    for et, xt, sym, r in trades:
        while open_h and open_h[0][0] <= et:
            _, s = heapq.heappop(open_h)
            open_syms.pop(s, None)
        if len(open_h) >= slots or sym in open_syms:
            continue
        heapq.heappush(open_h, (xt, sym))
        open_syms[sym] = xt
        taken.append((et, xt, sym, r))
    return taken


# Config picked on Oct-2025..Oct-2026 data; evaluated untouched on holdout.
FROZEN = dict(L=10, R=3.0, W=12, pct=60, volr=0.0, risk=(1.0, 5.0), fvg=True)


def run_frozen(data, hold):
    cfg = FROZEN
    trades = []
    for sym, df in data.items():
        obs, ohlc = find_obs(df, cfg["L"])
        idx = df.index
        for ob in obs:
            if ob["pct"] < cfg["pct"] or ob["volr"] < cfg["volr"]:
                continue
            if cfg["fvg"] and not ob["fvg"]:
                continue
            t = sim_trade(ob, ohlc, cfg["R"], cfg["W"], hold)
            if t is None:
                continue
            j, k, ret, risk = t
            if not cfg["risk"][0] <= risk * 100 <= cfg["risk"][1]:
                continue
            trades.append((idx[j], idx[k], sym, ret))
    print(f"frozen cfg {cfg}")
    n, wr, net, pf = stats([t[3] for t in trades])
    print(f"every signal: n={n} wr={wr:.1f}% net=${net:.0f} PF={pf:.2f}")
    tk = pd.DataFrame(portfolio(trades), columns=["et", "xt", "sym", "ret"])
    n, wr, net, pf = stats(list(tk.ret))
    print(f"portfolio 5 slots x ${TRADE_USDT:.0f}: n={n} wr={wr:.1f}% net=${net:.0f} PF={pf:.2f}")
    tk["m"] = tk.et.dt.strftime("%Y-%m")
    monthly = (tk.groupby("m").ret.sum() * TRADE_USDT).round(0)
    print("monthly $: " + " ".join(f"{k[2:]}:{int(v):+d}" for k, v in monthly.items()))
    print(f"positive months: {(monthly > 0).sum()}/{len(monthly)}")
    eq = (tk.sort_values("xt").ret * TRADE_USDT).cumsum()
    print(f"max drawdown: ${(eq.cummax() - eq).max():.0f}")


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1h"
    data = load(tf)
    if "--frozen" in sys.argv:
        print(f"{len(data)} symbols ({tf})")
        run_frozen(data, 7 * 24 if tf.startswith("1h") else 7 * 96)
        return
    print(f"{len(data)} symbols ({tf})")
    t_all = pd.concat([d.index.to_series() for d in data.values()])
    t0, t1 = t_all.min(), t_all.max()
    split = t0 + (t1 - t0) * IS_FRAC
    print(f"range {t0} .. {t1}; in-sample until {split}")

    Ls = [3, 5, 10, 20]
    Rs = [1.0, 1.5, 2.0, 3.0]
    WAITs = [12, 48]
    HOLD = 7 * 24 if tf == "1h" else 7 * 96
    PCTs = [0, 30, 60]
    VOLRs = [0, 1.5, 2.5]
    TRENDs = [False, True]
    RISKs = [(0.3, 8.0), (1.0, 5.0)]

    # trades per (L, R, wait): list of (feat..., entry_ts, exit_ts, sym, ret, risk)
    rows = []
    for L in Ls:
        cache = {sym: find_obs(df, L) for sym, df in data.items()}
        n_obs = sum(len(v[0]) for v in cache.values())
        print(f"L={L}: {n_obs} bullish OBs", flush=True)
        for R, W in product(Rs, WAITs):
            for sym, (obs, ohlc) in cache.items():
                idx = data[sym].index
                for ob in obs:
                    t = sim_trade(ob, ohlc, R, W, HOLD)
                    if t is None:
                        continue
                    j, k, ret, risk = t
                    rows.append((L, R, W, ob["pct"], ob["volr"], ob["trend"], risk * 100,
                                 ob["fvg"], ob["htf"], idx[j], idx[k], sym, ret))
    df = pd.DataFrame(rows, columns=["L", "R", "W", "pct", "volr", "trend", "risk",
                                     "fvg", "htf", "et", "xt", "sym", "ret"])
    print(f"{len(df)} simulated trades total; with FVG {df.fvg.mean()*100:.0f}%, "
          f"HTF bullish {df.htf.mean()*100:.0f}%")

    FVGs = [False, True]
    HTFs = [False, True]
    res = []
    for (L, R, W), g in df.groupby(["L", "R", "W"]):
        for P, V, T, (rlo, rhi), F, H in product(PCTs, VOLRs, TRENDs, RISKs, FVGs, HTFs):
            m = (g.pct >= P) & (g.volr >= V) & (g.risk >= rlo) & (g.risk <= rhi)
            if T:
                m &= g.trend
            if F:
                m &= g.fvg
            if H:
                m &= g.htf
            s = g[m]
            if len(s) < 30:
                continue
            ins = s[s.et < split]
            oos = s[s.et >= split]
            ni, wi, pi, pfi = stats(list(ins.ret))
            no, wo, po, pfo = stats(list(oos.ret))
            res.append((pi, L, R, W, P, V, T, rlo, rhi, F, H, ni, wi, pfi, no, wo, po, pfo))
    res.sort(key=lambda x: -x[0])
    hdr = (" L    R   W  pct volr trd risk   fvg htf | IS: n    wr%     net$    PF  | "
           "OOS: n   wr%     net$    PF")
    print("\n=== top 25 by in-sample net (every OB taken, $500/trade) ===")
    print(hdr)
    for r in res[:25]:
        pi, L, R, W, P, V, T, rlo, rhi, F, H, ni, wi, pfi, no, wo, po, pfo = r
        print(f"{L:2d} {R:4.1f} {W:3d} {P:4d} {V:4.1f} {int(T):3d} {rlo:.1f}-{rhi:.0f} "
              f"{int(F):3d} {int(H):3d} | "
              f"{ni:5d} {wi:5.1f} {pi:8.0f} {pfi:5.2f} | {no:5d} {wo:5.1f} {po:8.0f} {pfo:5.2f}")
    pos_both = [r for r in res if r[0] > 0 and r[16] > 0]
    print(f"\nconfigs profitable IS: {sum(1 for r in res if r[0] > 0)}/{len(res)}; "
          f"IS and OOS: {len(pos_both)}")

    print("\n=== filter effect across all configs (median PF, share OOS-profitable) ===")
    rd = pd.DataFrame(res, columns=["pi", "L", "R", "W", "P", "V", "T", "rlo", "rhi", "F", "H",
                                    "ni", "wi", "pfi", "no", "wo", "po", "pfo"])
    for col in ("F", "H", "T"):
        for val in (False, True):
            s = rd[rd[col] == val]
            print(f"{col}={int(val)}: configs={len(s):4d} medPF IS={s.pfi.median():.3f} "
                  f"OOS={s.pfo.median():.3f}  OOS>0: {(s.po > 0).mean()*100:.0f}%")
    s = rd[rd.F & rd.H]
    print(f"F=1&H=1: configs={len(s):4d} medPF IS={s.pfi.median():.3f} "
          f"OOS={s.pfo.median():.3f}  OOS>0: {(s.po > 0).mean()*100:.0f}%")

    print("\n=== portfolio (5 slots, 1 pos/symbol) for top-5 IS configs ===")
    for r in res[:5]:
        pi, L, R, W, P, V, T, rlo, rhi, F, H = r[:11]
        g = df[(df.L == L) & (df.R == R) & (df.W == W) & (df.pct >= P) & (df.volr >= V)
               & (df.risk >= rlo) & (df.risk <= rhi)]
        if T:
            g = g[g.trend]
        if F:
            g = g[g.fvg]
        if H:
            g = g[g.htf]
        taken = portfolio(list(zip(g.et, g.xt, g.sym, g.ret)))
        tk = pd.DataFrame(taken, columns=["et", "xt", "sym", "ret"])
        tk["m"] = tk.et.dt.strftime("%Y-%m")
        monthly = (tk.groupby("m").ret.sum() * TRADE_USDT).round(0)
        n, wr, net, pf = stats(list(tk.ret))
        print(f"L{L} R{R} W{W} pct{P} volr{V} trend{int(T)} risk{rlo}-{rhi} fvg{int(F)} "
              f"htf{int(H)}: n={n} wr={wr:.1f}% net=${net:.0f} PF={pf:.2f}")
        print("   monthly $: " + " ".join(f"{k[2:]}:{int(v):+d}" for k, v in monthly.items()))


if __name__ == "__main__":
    main()
