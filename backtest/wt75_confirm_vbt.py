#!/usr/bin/env python3
"""WaveTrend wt1 <= -75 bottom with market-level / price confirmation
(vectorbt, no volume). Base event: wt1 crosses below -75 on bar close.

Confirmations (all evaluated on the event bar unless noted):
  breadth B  - share of live symbols with wt1 < -60 >= B  (B in 0/10/20/30%)
  btc        - none | os (BTC wt1 < -60) | bull (last completed daily BTC
               bar has wt1 > wt2)
  price      - none | brk: one of the next 3 bars closes above the event
               bar high; entry at the open after that confirming bar
Exits as wt75_vbt.py (ob60 / xdn0 / tp5sl5 / tp10sl8). Entry next open.

PASS (fixed before running): PF >= 1.10 and n >= 30 in every period, in
both modes (every signal $500, and 2500 USDT shared = 5 slots).

Usage: python wt75_confirm_vbt.py
"""
import warnings
from itertools import product

import pandas as pd

from wt75_vbt import (EXITS, PERIODS, WARMUP, daily_bull, load, run_pf, stats,
                      wavetrend, wide)

warnings.filterwarnings("ignore")

TFS = ["1h", "4h"]
BREADTHS = [0.0, 0.10, 0.20, 0.30]
BTCS = ["none", "os", "bull"]
PRICES = ["none", "brk"]
OS, BREADTH_OS = -75.0, -60.0
PASS_PF, PASS_N = 1.10, 30
BTC = "BTCUSDT"


def prepare(data, tf):
    w = wide(data, tf)
    o, h, l, c = w["open"], w["high"], w["low"], w["close"]
    w1, w2 = wavetrend(h, l, c)
    p1, q1 = w1.shift(1), w2.shift(1)
    has = c.notna()
    live = has.cumsum() > WARMUP
    touch = (w1 < OS) & (p1 >= OS) & live
    breadth = ((w1 < BREADTH_OS) & live).sum(axis=1) / live.sum(axis=1).clip(lower=1)
    btc = {"none": pd.Series(True, index=c.index),
           "os": w1[BTC] < BREADTH_OS,
           "bull": daily_bull(data, c.index, tf)[BTC]}
    xdn = (w1 < w2) & (p1 >= q1)
    ex_sig = {"ob60": (w1 > 60) & (p1 <= 60), "xdn0": xdn & (w1 > 0)}
    px = {k: v.ffill().bfill() for k, v in w.items()}
    return px, h, c, touch, breadth, btc, ex_sig, has


def entries_for(h, c, ev, price):
    """ev: event mask on bar close -> entry mask (order at that bar's open)."""
    if price == "none":
        return ev.shift(1, fill_value=False)
    ref = h.where(ev).shift(1).ffill(limit=2)      # event high from bars k-1..k-3
    conf = (c > ref) & ref.notna()
    return conf.shift(1, fill_value=False)


def main():
    res = {}
    for pname, sub in PERIODS:
        data = load(sub)
        print(f"{pname}: {len(data)} symbols", flush=True)
        for tf in TFS:
            px, h, c, touch, breadth, btc, ex_sig, has = prepare(data, tf)
            none_x = pd.DataFrame(False, index=c.index, columns=c.columns)
            for B, bt, pr in product(BREADTHS, BTCS, PRICES):
                mkt = (breadth >= B) & btc[bt].reindex(c.index).fillna(False).astype(bool)
                ev = touch.mul(mkt, axis=0).astype(bool)
                ent = entries_for(h, c, ev, pr) & has
                for ex, (tp, sl) in EXITS.items():
                    xs = ex_sig.get(ex)
                    xs = xs.shift(1, fill_value=False) & has if xs is not None else none_x
                    for shared in (False, True):
                        res[(tf, B, bt, pr, ex, pname, shared)] = stats(
                            run_pf(px, ent, xs, tp, sl, shared))
            print(f"  {tf} done", flush=True)

    cfgs = list(product(TFS, BREADTHS, BTCS, PRICES, EXITS))
    rows = []
    for cfg in cfgs:
        ev = [res[(*cfg, p, False)] for p, _ in PERIODS]
        sh = [res[(*cfg, p, True)] for p, _ in PERIODS]
        rows.append((cfg, ev, sh))

    def ok(r):
        return all(s["pf"] >= PASS_PF and s["n"] >= PASS_N for s in r)

    def line(r):
        return " | ".join(f"n={s['n']:4d} PF={s['pf']:4.2f} ${s['net']:6.0f}" for s in r)

    rows.sort(key=lambda r: -min(s["pf"] for s in r[1] if s["n"] >= PASS_N)
              if all(s["n"] >= PASS_N for s in r[1]) else 0)
    print(f"\n{len(rows)} configs; rows with n>={PASS_N} in every period, "
          f"sorted by worst-period PF (every signal / shared 5 slots)")
    print(f"{'(tf, breadth, btc, price, exit)':40s} | "
          + " | ".join(f"{p:^28s}" for p, _ in PERIODS))
    shown = 0
    for cfg, ev, sh in rows:
        if not all(s["n"] >= PASS_N for s in ev):
            continue
        tag = "  PASS" if ok(ev) and ok(sh) else ("  pass-every" if ok(ev) else "")
        print(f"{str(cfg):40s} | {line(ev)}{tag}")
        print(f"{'   shared':40s} | {line(sh)}")
        shown += 1
        if shown >= 20:
            break
    print(f"\nPASS every-signal: {sum(ok(e) for _, e, _ in rows)}/{len(rows)}; "
          f"PASS both modes: {sum(ok(e) and ok(s) for _, e, s in rows)}/{len(rows)}")

    print("\neffect of each confirmation (median worst-period PF, every signal, "
          "configs with n>=30 everywhere):")
    df = pd.DataFrame([(*cfg, min(s["pf"] for s in ev),
                        all(s["n"] >= PASS_N for s in ev)) for cfg, ev, _ in rows],
                      columns=["tf", "B", "btc", "price", "ex", "worst", "enough"])
    df = df[df.enough]
    for col in ("B", "btc", "price", "tf", "ex"):
        print(f"  {col}: " + "  ".join(f"{k}={v:.2f}" for k, v in
                                       df.groupby(col).worst.median().items()))


if __name__ == "__main__":
    main()
