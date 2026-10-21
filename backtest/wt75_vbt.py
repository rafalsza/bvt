#!/usr/bin/env python3
"""vectorbt re-run of wt75_backtest.py (WaveTrend wt1 <= -75, no volume).

Same triggers / filters / exits / periods. Simulation is
vbt.Portfolio.from_signals on wide (time x symbol) frames:
- signal on bar close -> entry/exit order next bar at open (shifted signals,
  price=open); SL/TP intrabar from OHLC via sl_stop/tp_stop
- 2500 USDT shared cash, 500 USDT per entry, no partial fills, no pyramiding
  -> max 5 concurrent positions, one per symbol
- fees 0.1%/side, slippage 0.025%/order
- no time stop (vectorbt 1.0.0 from_signals has none)

Usage: python wt75_vbt.py
"""
import warnings

import numpy as np
import pandas as pd
import vectorbt as vbt

from wt_backtest import load

warnings.filterwarnings("ignore")

PERIODS = [("2022-23", "1h_until1095d"), ("2023-25", "1h_until365d"),
           ("2025-26", "1h")]
TFS = ["1h", "4h"]
TRIGGERS = ["touch", "up", "cross"]
FILTERS = ["none", "below200", "above200", "daily"]
EXITS = {"ob60": (None, 0.10), "xdn0": (None, 0.10),
         "tp5sl5": (0.05, 0.05), "tp10sl8": (0.10, 0.08)}
OS = -75.0
N1, N2 = 10, 21
WARMUP = 201
FEES, SLIP = 0.001, 0.00025
INIT_CASH, SIZE = 2500.0, 500.0
PASS_PF, PASS_N = 1.10, 30


def wide(data, tf):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    cols = {}
    for sym, df in data.items():
        f = df if tf == "1h" else df.resample(tf, label="left", closed="left").agg(agg)
        cols[sym] = f.dropna()
    out = {k: pd.DataFrame({s: f[k] for s, f in cols.items()}) for k in agg}
    return out


def wavetrend(h, l, c):
    ap = (h + l + c) / 3
    esa = ap.ewm(span=N1, adjust=False).mean()
    d = (ap - esa).abs().ewm(span=N1, adjust=False).mean()
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.ewm(span=N2, adjust=False).mean()
    return wt1, wt1.rolling(4).mean()


def daily_bull(data, idx, tf):
    """wt1 > wt2 of the last completed daily bar, known at our bar close."""
    d = wide(data, "1D")
    w1, w2 = wavetrend(d["high"], d["low"], d["close"])
    bull = (w1 > w2).astype(float).where(w2.notna())
    known = bull.shift(1)                      # label D carries day D-1 (complete at D)
    close_t = idx + pd.Timedelta(tf)
    m = known.reindex(close_t, method="ffill")
    m.index = idx
    return m.fillna(0).astype(bool)


def signals(data, tf):
    w = wide(data, tf)
    o, h, l, c = w["open"], w["high"], w["low"], w["close"]
    w1, w2 = wavetrend(h, l, c)
    p1, q1 = w1.shift(1), w2.shift(1)
    live = c.notna().cumsum() > WARMUP
    xup = (w1 > w2) & (p1 <= q1)
    xdn = (w1 < w2) & (p1 >= q1)
    # min wt1 inside the current bearish segment (since last cross-down)
    seg = xdn.cumsum()
    segmin = pd.DataFrame({s: w1[s].groupby(seg[s]).cummin() for s in w1.columns})
    trig = {
        "touch": (w1 < OS) & (p1 >= OS),
        "up": (w1 >= OS) & (p1 < OS),
        "cross": xup & (segmin.shift(1) <= OS) & (seg > 0),
    }
    ema = c.ewm(span=200, adjust=False).mean()
    flt = {"none": pd.DataFrame(True, index=c.index, columns=c.columns),
           "below200": c < ema, "above200": c > ema,
           "daily": daily_bull(data, c.index, tf)}
    ex_sig = {"ob60": (w1 > 60) & (p1 <= 60), "xdn0": xdn & (w1 > 0)}
    trig = {k: v & live for k, v in trig.items()}
    # price frames for vbt: ffill gaps, bfill pre-listing (no signals there)
    px = {k: v.ffill().bfill() for k, v in w.items()}
    return px, trig, flt, ex_sig, c.notna()


def run_pf(px, entries, exits, tp, sl, shared):
    """shared=True: 2500 USDT common cash (<=5 slots, losses shrink capacity).
    shared=False: every signal taken at fixed 500 USDT (per-symbol cash pool
    large enough, no compounding) - the statistic used for PASS."""
    kw = dict(close=px["close"], entries=entries, exits=exits, price=px["open"],
              open=px["open"], high=px["high"], low=px["low"], sl_stop=sl,
              fees=FEES, slippage=SLIP, size=SIZE, size_type="value",
              allow_partial=False, accumulate=False)
    if shared:
        kw.update(init_cash=INIT_CASH, cash_sharing=True, group_by=True, call_seq="auto")
    else:
        kw.update(init_cash=1e9)
    if tp:
        kw["tp_stop"] = tp
    return vbt.Portfolio.from_signals(**kw)


def stats(pf):
    tr = pf.trades.records_readable
    tr = tr[tr["Status"] == "Closed"]
    n = len(tr)
    if not n:
        return dict(n=0, pf=0.0, net=0.0, wr=0.0, pos=0, months=0, dd=0.0)
    tr = tr.sort_values("Exit Timestamp")
    pnl = tr["PnL"].values
    gl = -pnl[pnl < 0].sum()
    monthly = tr.groupby(tr["Exit Timestamp"].dt.to_period("M"))["PnL"].sum()
    eq = np.cumsum(pnl)
    return dict(n=n, pf=pnl[pnl > 0].sum() / gl if gl else 99.0, net=float(pnl.sum()),
                wr=(pnl > 0).mean() * 100, pos=int((monthly > 0).sum()),
                months=len(monthly), dd=float((np.maximum.accumulate(eq) - eq).max()))


def main():
    res = {}
    for pname, sub in PERIODS:
        data = load(sub)
        print(f"{pname}: {len(data)} symbols", flush=True)
        for tf in TFS:
            px, trig, flt, ex_sig, has = signals(data, tf)
            for t in TRIGGERS:
                for f in FILTERS:
                    ent = (trig[t] & flt[f]).shift(1, fill_value=False) & has
                    for ex, (tp, sl) in EXITS.items():
                        xs = ex_sig.get(ex)
                        xs = (xs.shift(1, fill_value=False) & has) if xs is not None \
                            else pd.DataFrame(False, index=ent.index, columns=ent.columns)
                        res[(tf, t, f, ex, pname)] = stats(run_pf(px, ent, xs, tp, sl, False))
                        res[(tf, t, f, ex, pname, "shared")] = stats(
                            run_pf(px, ent, xs, tp, sl, True))
            print(f"  {tf} done", flush=True)

    rows = []
    for tf in TFS:
        for t in TRIGGERS:
            for f in FILTERS:
                for ex in EXITS:
                    rows.append(((tf, t, f, ex), [res[(tf, t, f, ex, p)] for p, _ in PERIODS]))

    def ok(r):
        return all(s["pf"] >= PASS_PF and s["n"] >= PASS_N for s in r)

    rows.sort(key=lambda r: -min(s["pf"] for s in r[1]))
    print(f"\n{len(rows)} configs (vectorbt, every signal $500); sorted by worst-period PF")
    print(f"{'config':38s} | " + " | ".join(f"{p:^28s}" for p, _ in PERIODS))
    for cfg, r in rows[:25]:
        cells = " | ".join(f"n={s['n']:4d} PF={s['pf']:4.2f} ${s['net']:6.0f}" for s in r)
        print(f"{str(cfg):38s} | {cells}{'  PASS' if ok(r) else ''}")
    print(f"\nPASS (PF>={PASS_PF} and n>={PASS_N} in all 3 periods): "
          f"{sum(ok(r) for _, r in rows)}/{len(rows)}")
    print("\nshared 2500 USDT / 5 slots for the top-5 rows above:")
    for cfg, _ in rows[:5]:
        cells = " | ".join(
            f"n={s['n']:4d} PF={s['pf']:4.2f} ${s['net']:6.0f}"
            for s in (res[(*cfg, p, "shared")] for p, _ in PERIODS))
        print(f"{str(cfg):38s} | {cells}")
    print("\nrs_wavetrend.py logic (touch, below200, ob60):")
    for tf in TFS:
        for p, _ in PERIODS:
            for mode, key in (("every", (tf, "touch", "below200", "ob60", p)),
                              ("shared", (tf, "touch", "below200", "ob60", p, "shared"))):
                s = res[key]
                print(f"  {tf} {p} {mode:6s}: n={s['n']} wr={s['wr']:.1f}% "
                      f"net=${s['net']:.0f} PF={s['pf']:.2f} "
                      f"months+={s['pos']}/{s['months']} DD=${s['dd']:.0f}")


if __name__ == "__main__":
    main()
