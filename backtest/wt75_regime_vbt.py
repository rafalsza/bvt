#!/usr/bin/env python3
"""Capitulation buy (4h wt1 crosses below -75) with a long-horizon BTC
regime filter, vectorbt. POST-HOC: the idea came from seeing the 2025-26
bear failure, and there is only one bear period to check it on.

Regime (last completed daily BTC bar, data/btc_1d.pkl from 2021):
  none | sma200: close > SMA200 | sma100: close > SMA100
Market condition: none | btc_os (BTC 4h wt1 < -60, the best shape so far)
Exits as wt75_vbt.py. Both modes (every signal / 2500 shared, 5 slots).
PASS: PF >= 1.10 and n >= 30 in every period, both modes.

Usage: python wt75_regime_vbt.py
"""
import os
import warnings
from itertools import product

import pandas as pd

from wt75_confirm_vbt import BTC, PASS_N, PASS_PF, entries_for, prepare
from wt_backtest import DATA_ROOT
from wt75_vbt import EXITS, PERIODS, load, run_pf, stats

warnings.filterwarnings("ignore")

TF = "4h"
REGIMES = ["none", "sma200", "sma100"]
MARKET = ["none", "btc_os"]


def btc_regime(idx, tf, n):
    d = pd.read_pickle(os.path.join(DATA_ROOT, "btc_1d.pkl"))["close"]
    up = (d > d.rolling(n).mean()).astype(float).where(d.rolling(n).count() == n)
    known = up.shift(1)                       # day D-1 complete at D 00:00
    m = known.reindex(idx + pd.Timedelta(tf), method="ffill")
    m.index = idx
    return m.fillna(0).astype(bool)


def main():
    res, share = {}, {}
    for pname, sub in PERIODS:
        data = load(sub)
        px, h, c, touch, breadth, btc, ex_sig, has = prepare(data, TF)
        reg = {"none": pd.Series(True, index=c.index),
               "sma200": btc_regime(c.index, TF, 200),
               "sma100": btc_regime(c.index, TF, 100)}
        share[pname] = {k: float(v.mean()) for k, v in reg.items()}
        mk = {"none": pd.Series(True, index=c.index), "btc_os": btc["os"]}
        none_x = pd.DataFrame(False, index=c.index, columns=c.columns)
        for r, m in product(REGIMES, MARKET):
            ev = touch.mul(reg[r] & mk[m], axis=0).astype(bool)
            ent = entries_for(h, c, ev, "none") & has
            for ex, (tp, sl) in EXITS.items():
                xs = ex_sig.get(ex)
                xs = xs.shift(1, fill_value=False) & has if xs is not None else none_x
                for sh in (False, True):
                    res[(r, m, ex, pname, sh)] = stats(run_pf(px, ent, xs, tp, sl, sh))
        print(f"{pname}: {len(data)} symbols, BTC regime ON share: "
              + " ".join(f"{k}={v*100:.0f}%" for k, v in share[pname].items()), flush=True)

    def ok(rr):
        return all(s["pf"] >= PASS_PF and s["n"] >= PASS_N for s in rr)

    def line(rr):
        return " | ".join(f"n={s['n']:4d} PF={s['pf']:4.2f} ${s['net']:6.0f}" for s in rr)

    print(f"\n{'(regime, market, exit)':30s} | " + " | ".join(f"{p:^28s}" for p, _ in PERIODS))
    npass = 0
    for r, m, ex in product(REGIMES, MARKET, EXITS):
        ev = [res[(r, m, ex, p, False)] for p, _ in PERIODS]
        sh = [res[(r, m, ex, p, True)] for p, _ in PERIODS]
        tag = "  PASS" if ok(ev) and ok(sh) else ("  pass-every" if ok(ev) else "")
        npass += bool(tag == "  PASS")
        print(f"{str((r, m, ex)):30s} | {line(ev)}{tag}")
        print(f"{'   shared':30s} | {line(sh)}")
    print(f"\nPASS both modes: {npass}/{len(REGIMES) * len(MARKET) * len(EXITS)}")


if __name__ == "__main__":
    main()
