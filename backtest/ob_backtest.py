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
    cur_high = -1
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
                        prev_idx = k
                else:
                    prev_type, prev_idx = -1, k
        last_high[i] = cur_high
    return last_high


def find_obs(df, L):
    o, h, l, c, v = (df[x].values.astype(float) for x in ("open", "high", "low", "close", "volume"))
    last_high = confirmed_swings(h, l, L)
    crossed = set()
    vavg = pd.Series(v).rolling(50, min_periods=10).mean().values
    ema = pd.Series(c).ewm(span=200, adjust=False).mean().values
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
                        trend=c[i] > ema[i], disp=(c[i] - top) / top * 100))
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


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1h"
    data = load(tf)
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
                                 idx[j], idx[k], sym, ret))
    df = pd.DataFrame(rows, columns=["L", "R", "W", "pct", "volr", "trend", "risk",
                                     "et", "xt", "sym", "ret"])
    print(f"{len(df)} simulated trades total")

    res = []
    for (L, R, W), g in df.groupby(["L", "R", "W"]):
        for P, V, T, (rlo, rhi) in product(PCTs, VOLRs, TRENDs, RISKs):
            m = (g.pct >= P) & (g.volr >= V) & (g.risk >= rlo) & (g.risk <= rhi)
            if T:
                m &= g.trend
            s = g[m]
            if len(s) < 30:
                continue
            ins = s[s.et < split]
            oos = s[s.et >= split]
            ni, wi, pi, pfi = stats(list(ins.ret))
            no, wo, po, pfo = stats(list(oos.ret))
            res.append((pi, L, R, W, P, V, T, rlo, rhi, ni, wi, pfi, no, wo, po, pfo))
    res.sort(key=lambda x: -x[0])
    hdr = (" L    R   W  pct volr trd risk     | IS: n    wr%     net$    PF  | "
           "OOS: n   wr%     net$    PF")
    print("\n=== top 20 by in-sample net (every OB taken, $500/trade) ===")
    print(hdr)
    for r in res[:20]:
        pi, L, R, W, P, V, T, rlo, rhi, ni, wi, pfi, no, wo, po, pfo = r
        print(f"{L:2d} {R:4.1f} {W:3d} {P:4d} {V:4.1f} {int(T):3d} {rlo:.1f}-{rhi:.0f}  | "
              f"{ni:5d} {wi:5.1f} {pi:8.0f} {pfi:5.2f} | {no:5d} {wo:5.1f} {po:8.0f} {pfo:5.2f}")
    pos_both = [r for r in res if r[0] > 0 and r[14] > 0]
    print(f"\nconfigs profitable IS: {sum(1 for r in res if r[0] > 0)}/{len(res)}; "
          f"IS and OOS: {len(pos_both)}")

    print("\n=== portfolio (5 slots, 1 pos/symbol) for top-5 IS configs ===")
    for r in res[:5]:
        pi, L, R, W, P, V, T, rlo, rhi = r[:9]
        g = df[(df.L == L) & (df.R == R) & (df.W == W) & (df.pct >= P) & (df.volr >= V)
               & (df.risk >= rlo) & (df.risk <= rhi)]
        if T:
            g = g[g.trend]
        taken = portfolio(list(zip(g.et, g.xt, g.sym, g.ret)))
        tk = pd.DataFrame(taken, columns=["et", "xt", "sym", "ret"])
        tk["m"] = tk.et.dt.strftime("%Y-%m")
        monthly = (tk.groupby("m").ret.sum() * TRADE_USDT).round(0)
        n, wr, net, pf = stats(list(tk.ret))
        print(f"L{L} R{R} W{W} pct{P} volr{V} trend{int(T)} risk{rlo}-{rhi}: "
              f"n={n} wr={wr:.1f}% net=${net:.0f} PF={pf:.2f}")
        print("   monthly $: " + " ".join(f"{k[2:]}:{int(v):+d}" for k, v in monthly.items()))


if __name__ == "__main__":
    main()
