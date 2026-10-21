#!/usr/bin/env python3
"""WaveTrend wt1 <= -75 study (no volume filters), evaluated in all three
regimes; a config only counts if it is profitable in every period.

Triggers (signal on bar close, entry next bar open):
  touch - wt1 drops below -75                       (rs_wavetrend.py style)
  up    - wt1 climbs back above -75
  cross - wt1 crosses over wt2 after reaching <= -75 in the bearish segment
Filters: none | below200 (close < EMA200, as in rs_wavetrend.py) |
         above200 | daily (last completed 1D bar wt1 > wt2; 1h -> 4h HTF)
Exits (fixed SL checked first, same-bar SL+TP -> SL, max 14 days):
  ob60     - wt1 crosses above +60 (rs_wavetrend.py sell), SL -10%
  xdn0     - wt1 crosses below wt2 while wt1 > 0, SL -10%
  tp5sl5   - TP +5% / SL -5%
  tp10sl8  - TP +10% / SL -8%

Usage: python wt75_backtest.py
"""
import numpy as np
import pandas as pd

from wt_backtest import (FEE, STOP_SLIP, MAX_HOLD, fmt, htf_bull, load,
                         portfolio, resample, summary, wavetrend)

PERIODS = [("2022-23", "1h_until1095d"), ("2023-25", "1h_until365d"),
           ("2025-26", "1h")]
TFS = ["1h", "4h"]
TRIGGERS = ["touch", "up", "cross"]
FILTERS = ["none", "below200", "above200", "daily"]
EXITS = {"ob60": (None, 10.0), "xdn0": (None, 10.0),
         "tp5sl5": (5.0, 5.0), "tp10sl8": (10.0, 8.0)}
OS = -75.0
PASS_PF, PASS_N = 1.10, 30


def daily_bull(df, tf):
    if tf == "4h":
        return htf_bull(df, "4h")          # 4h -> 1D
    # 1h: use the daily bar too, mapped onto 1h bars
    hdf = resample(df, "1D")
    w1, w2 = wavetrend(*(hdf[x].values.astype(float) for x in ("high", "low", "close")))
    k = np.searchsorted(hdf.index.values,
                        (df.index + pd.Timedelta("1h") - pd.Timedelta("1D")).values,
                        side="right") - 1
    out = np.zeros(len(df), dtype=bool)
    ok = k >= 0
    out[ok] = (w1 > w2)[k[ok]]
    return out


def events(df, tf):
    f = resample(df, tf)
    o, h, l, c = (f[x].values.astype(float) for x in ("open", "high", "low", "close"))
    w1, w2 = wavetrend(h, l, c)
    ema = pd.Series(c).ewm(span=200, adjust=False).mean().values
    db = daily_bull(df, tf)
    ev = []
    seg_min = None
    for i in range(201, len(c) - 1):
        if np.isnan(w2[i - 1]):
            continue
        if w1[i] < w2[i] and w1[i - 1] >= w2[i - 1]:
            seg_min = w1[i]
        elif seg_min is not None:
            seg_min = min(seg_min, w1[i])
        trig = []
        if w1[i] < OS <= w1[i - 1]:
            trig.append("touch")
        if w1[i] >= OS > w1[i - 1]:
            trig.append("up")
        if w1[i] > w2[i] and w1[i - 1] <= w2[i - 1]:
            if seg_min is not None and seg_min <= OS:
                trig.append("cross")
            seg_min = None
        if not trig:
            continue
        flt = {"none": True, "below200": c[i] < ema[i], "above200": c[i] > ema[i],
               "daily": bool(db[i])}
        for t in trig:
            ev.append((i, t, flt))
    return f.index, (o, h, l, c, w1, w2), ev


def sim(arr, i, exit_name, max_hold):
    o, h, l, c, w1, w2 = arr
    tp_pct, sl_pct = EXITS[exit_name]
    j = i + 1
    entry = o[j]
    sl = entry * (1 - sl_pct / 100)
    tp = entry * (1 + tp_pct / 100) if tp_pct else None
    n = len(c)
    for k in range(j, min(n, j + max_hold)):
        if l[k] <= sl:
            return j, k, min(o[k], sl) / entry - 1 - 2 * FEE - STOP_SLIP
        if tp is not None and h[k] >= tp:
            return j, k, max(o[k], tp) / entry - 1 - 2 * FEE
        if k + 1 < n and k > 0:
            if exit_name == "ob60" and w1[k] > 60 >= w1[k - 1]:
                return j, k + 1, o[k + 1] / entry - 1 - 2 * FEE
            if exit_name == "xdn0" and w1[k] < w2[k] and w1[k - 1] >= w2[k - 1] \
                    and w1[k] > 0:
                return j, k + 1, o[k + 1] / entry - 1 - 2 * FEE
    k = min(n - 1, j + max_hold)
    return j, k, c[k] / entry - 1 - 2 * FEE


def run(data):
    rows = []
    for tf in TFS:
        for sym, df in data.items():
            idx, arr, evs = events(df, tf)
            for i, trig, flt in evs:
                for ex in EXITS:
                    j, k, r = sim(arr, i, ex, MAX_HOLD[tf])
                    rows.append((tf, trig, ex, flt["none"], flt["below200"],
                                 flt["above200"], flt["daily"], idx[j], idx[k], sym, r))
    return pd.DataFrame(rows, columns=["tf", "trig", "ex", "none", "below200",
                                       "above200", "daily", "et", "xt", "sym", "ret"])


def main():
    per = {}
    for name, sub in PERIODS:
        data = load(sub)
        print(f"{name}: {len(data)} symbols", flush=True)
        per[name] = run(data)

    rows = []
    for tf in TFS:
        for trig in TRIGGERS:
            for flt in FILTERS:
                for ex in EXITS:
                    res = []
                    for name, _ in PERIODS:
                        d = per[name]
                        g = d[(d.tf == tf) & (d.trig == trig) & (d.ex == ex) & d[flt]]
                        res.append(summary(portfolio(g)))
                    rows.append(((tf, trig, flt, ex), res))

    def ok(res):
        return all(s["pf"] >= PASS_PF and s["n"] >= PASS_N for s in res)

    rows.sort(key=lambda r: -min(s["pf"] for s in r[1]))
    print(f"\n{len(rows)} configs; sorted by worst-period PF")
    print(f"{'config':38s} | " + " | ".join(f"{n:^28s}" for n, _ in PERIODS))
    for cfg, res in rows[:25]:
        cells = " | ".join(f"n={s['n']:4d} PF={s['pf']:4.2f} ${s['net']:6.0f}" for s in res)
        print(f"{str(cfg):38s} | {cells}{'  PASS' if ok(res) else ''}")
    print(f"\nPASS (PF>={PASS_PF} and n>={PASS_N} in all 3 periods): "
          f"{sum(ok(r) for _, r in rows)}/{len(rows)}")

    print("\nrs_wavetrend.py logic (touch, below200, ob60):")
    for tf in TFS:
        res = next(r for c, r in rows if c == (tf, "touch", "below200", "ob60"))
        for (name, _), s in zip(PERIODS, res):
            print(f"  {tf} {name}: {fmt(s)}")


if __name__ == "__main__":
    main()
