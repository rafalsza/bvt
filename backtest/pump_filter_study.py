#!/usr/bin/env python3
"""Pump-signal filter study on recorded 10s snapshots.

Extends replay_snapshots.py: re-parses ticks WITH volume and change_24h,
extracts extra per-event features, then sweeps entry filters on top of the
existing loose gates. Exit outcomes are precomputed once per exit config so
filter sweeps are cheap.

Features per event (all causal, known at signal tick):
  rng, net, lvm, tsm        - existing gates (range, net gain, last-vs-max,
                              ticks since window max)
  acc3                      - % of window range gained in the last 3 ticks
  pretrend                  - net % move over the 18 ticks BEFORE the window
  volz                      - window traded volume vs symbol's median window
                              volume over the trailing hour (log ratio)
  chg24                     - ticker 24h change at signal time
  hour                      - UTC hour
"""
import csv
import gzip
import heapq
import math
import os
import pickle
import sys
from array import array
from collections import deque
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "snapshot_data")
CACHE = os.path.join(DATA_DIR, "parsed_v2.pkl")

N = 18                      # ring window (18 x ~10s ~= 3min)
FEE = 0.002                 # round trip
TRADE_USDT = 500.0
MAX_FORWARD = 3000
MAX_HOLD_SEC = 8 * 3600
VOL_LOOKBACK = 360          # ~1h of ticks for volume baseline


def load_data():
    """sym -> (ts[i], price[f], volume[d], chg24[f])"""
    if os.path.exists(CACHE):
        print("loading pickle cache...", flush=True)
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    data = {}
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv.gz"):
            continue
        print(f"parsing {fn} ...", flush=True)
        with gzip.open(os.path.join(DATA_DIR, fn), "rt") as f:
            for row in csv.reader(f):
                if len(row) < 5 or row[0] == "ts":
                    continue
                try:
                    ep = int(datetime.strptime(row[0][:19], "%Y-%m-%dT%H:%M:%S").timestamp())
                except ValueError:
                    continue
                d = data.get(row[1])
                if d is None:
                    d = data[row[1]] = (array("i"), array("f"), array("d"), array("f"))
                d[0].append(ep)
                d[1].append(float(row[2]))
                d[2].append(float(row[3]) if row[3] else 0.0)
                d[3].append(float(row[4]) if row[4] else 0.0)
    for s in data:
        ts, ps, vs, cs = data[s]
        order = sorted(range(len(ts)), key=ts.__getitem__)
        data[s] = (
            array("i", [ts[i] for i in order]),
            array("f", [ps[i] for i in order]),
            array("d", [vs[i] for i in order]),
            array("f", [cs[i] for i in order]),
        )
    with open(CACHE, "wb") as f:
        pickle.dump(data, f, protocol=4)
    return data


def window_events(ts, ps, vs, cs, min_chg=2.0, min_net=0.5):
    """Yield (idx, feats tuple). Loosest gates only."""
    dmax = deque()
    dmin = deque()
    vol_hist = deque()  # (idx, window traded vol) for trailing median-ish baseline
    for i in range(len(ps)):
        p = ps[i]
        while dmax and ps[dmax[-1]] <= p:
            dmax.pop()
        dmax.append(i)
        while dmin and ps[dmin[-1]] >= p:
            dmin.pop()
        dmin.append(i)
        if i < N:
            continue
        lo = i - N + 1
        while dmax[0] < lo:
            dmax.popleft()
        while dmin[0] < lo:
            dmin.popleft()
        mx, mn = ps[dmax[0]], ps[dmin[0]]
        rng = (mx - mn) / mn * 100
        # traded volume inside window (24h cumulative -> delta); may reset/neg
        wvol = max(0.0, vs[i] - vs[lo - 1]) if lo > 0 else 0.0
        # maintain trailing baseline of window volumes
        vol_hist.append(wvol)
        while len(vol_hist) > VOL_LOOKBACK:
            vol_hist.popleft()
        if rng < min_chg:
            continue
        net = (p - ps[lo]) / ps[lo] * 100
        if net < min_net:
            continue
        lvm = (p - mx) / mx * 100
        tsm = i - dmax[0]
        # acceleration: share of range covered in last 3 ticks
        p3 = ps[i - 3] if i >= 3 else ps[lo]
        acc3 = (p - p3) / (mx - mn) * 100 if mx > mn else 0.0
        # pre-window trend: move over the 18 ticks before the window
        pre = (ps[lo] - ps[lo - N]) / ps[lo - N] * 100 if i >= 2 * N else 0.0
        # volume baseline: median of trailing window volumes (excl current)
        volz = 0.0
        if len(vol_hist) > 60:
            srt = sorted(vol_hist)
            med = srt[len(srt) // 2]
            if med > 0 and wvol > 0:
                volz = math.log(wvol / med)
        hour = (ts[i] % 86400) // 3600
        yield (i, rng, net, lvm, tsm, acc3, pre, volz, cs[i], hour, wvol)


def simulate_exit(ps, ts, i0, sl, arm, trail, ttp):
    e = ps[i0]
    sl_p = e * (1 - sl / 100)
    arm_p = e * (1 + arm / 100)
    ttp_p = e * (1 + (arm + ttp) / 100)
    armed = False
    peak = e
    t0 = ts[i0]
    jmax = min(len(ps), i0 + MAX_FORWARD)
    for j in range(i0 + 1, jmax):
        p = ps[j]
        if ts[j] - t0 > MAX_HOLD_SEC:
            return (p / e - 1 - FEE), j
        if not armed:
            if p <= sl_p:
                return (p / e - 1 - FEE), j
            if p >= arm_p:
                armed = True
                peak = p
                if p >= ttp_p:
                    return (p / e - 1 - FEE), j
        else:
            if p > peak:
                peak = p
            if p <= peak * (1 - trail / 100):
                return (p / e - 1 - FEE), j
            if p >= ttp_p:
                return (p / e - 1 - FEE), j
    j = len(ps) - 1
    return (ps[j] / e - 1 - FEE), j


def stats(pnls):
    n = len(pnls)
    if not n:
        return 0, 0.0, 0.0
    wr = sum(1 for p in pnls if p > 0) / n * 100
    return n, wr, sum(pnls)


def main():
    data = load_data()
    print(f"{len(data)} symbols, {sum(len(v[0]) for v in data.values())} ticks")

    events = []  # (epoch, sym, idx, feats...)
    for sym, (ts, ps, vs, cs) in data.items():
        for ev in window_events(ts, ps, vs, cs):
            events.append((ts[ev[0]], sym) + ev)
    events.sort()
    print(f"{len(events)} raw signal events (loose gates)")

    # feature indices inside event tuple:
    # 0 epoch, 1 sym, 2 idx, 3 rng, 4 net, 5 lvm, 6 tsm, 7 acc3,
    # 8 pretrend, 9 volz, 10 chg24, 11 hour, 12 wvol

    # --- exit outcomes: one representative config + a small grid ---
    SLs = [2.0, 3.0]
    ARMs = [2.0, 3.0, 5.0]
    TRAILs = [0.5, 1.0]
    TTP = 1.0
    exits = [(s, a, t) for s in SLs for a in ARMs for t in TRAILs]
    out = {}
    for cfg in exits:
        sl, arm, tr = cfg
        res = array("f", [0.0]) * len(events)
        for k, e in enumerate(events):
            sym, i = e[1], e[2]
            r, _j = simulate_exit(data[sym][1], data[sym][0], i, sl, arm, tr, TTP)
            res[k] = r * 100
        out[cfg] = res
        print(f"exit cfg {cfg} done", flush=True)

    REF = (3.0, 5.0, 1.0)  # SL3, arm5, trail1

    def filt(e, chg=2.0, net=0.5, lvm=-99, tsm=None, acc3=None, pre=None,
             volz=None, chg24=None, hours=None, wvol=None):
        if e[3] < chg or e[4] < net or e[5] < lvm:
            return False
        if tsm is not None and e[6] > tsm:
            return False
        if acc3 is not None and e[7] < acc3:
            return False
        if pre is not None:
            lo_, hi_ = pre
            if not (lo_ <= e[8] <= hi_):
                return False
        if volz is not None and e[9] < volz:
            return False
        if chg24 is not None:
            lo_, hi_ = chg24
            if not (lo_ <= e[10] <= hi_):
                return False
        if hours is not None and e[11] not in hours:
            return False
        if wvol is not None and e[12] < wvol:
            return False
        return True

    def report(name, **kw):
        idxs = [k for k, e in enumerate(events) if filt(e, **kw)]
        line = f"{name:34s} n={len(idxs):5d}"
        for cfg in exits:
            n_, wr, s = stats([out[cfg][k] for k in idxs])
            line += f" | {cfg}: {wr:4.0f}% {s:8.1f}%"
        print(line)
        return idxs

    print("\n=== BASELINE (loose gates, per exit cfg: win% netsum%) ===")
    base = report("baseline chg2 net0.5")

    print("\n=== SINGLE-FILTER SLICES (ref exit SL3/arm5/tr1) ===")
    res = out[REF]

    def slice_report(name, **kw):
        idxs = [k for k, e in enumerate(events) if filt(e, **kw)]
        n_, wr, s = stats([res[k] for k in idxs])
        print(f"{name:34s} n={n_:5d} wr={wr:5.1f}% net={s:9.2f}% ${s*5:8.0f}")

    slice_report("baseline")
    for v in [2.5, 3.0, 3.5, 4.0, 5.0]:
        slice_report(f"rng>={v}", chg=v)
    for v in [1.0, 1.5, 2.0, 2.5, 3.0]:
        slice_report(f"net>={v}", net=v)
    for v in [-0.3, -0.5, -1.0, -1.5]:
        slice_report(f"lvm>={v}", lvm=v)
    for v in [0, 2, 4, 6]:
        slice_report(f"tsm<={v}", tsm=v)
    for v in [20, 40, 60, 80]:
        slice_report(f"acc3>={v}%", acc3=v)
    for v in [-99]:
        slice_report("acc3<=20 (slow grind)", acc3=None)  # placeholder
    for lo_, hi_ in [(-99, -0.5), (-0.5, 0.5), (0.5, 2.0), (2.0, 99)]:
        slice_report(f"pretrend in [{lo_},{hi_}]", pre=(lo_, hi_))
    for v in [0.0, 0.7, 1.4, 2.0]:
        slice_report(f"volz>={v:.1f} (x{math.exp(v):.1f} med)", volz=v)
    slice_report("volz<0 (no spike)", volz=None)  # informational
    for lo_, hi_ in [(-99, -5), (-5, -2), (-2, 2), (2, 5), (5, 99)]:
        slice_report(f"chg24 in [{lo_},{hi_}]", chg24=(lo_, hi_))
    for wv in [1000, 5000, 20000, 100000]:
        slice_report(f"window vol>={wv} USDT", wvol=wv)

    print("\n=== HOUR OF DAY (ref exit) ===")
    for h in range(0, 24, 4):
        slice_report(f"hours {h}-{h+3} UTC", hours=set(range(h, h + 4)))

    print("\n=== TWO-FILTER COMBOS on promising singles (ref exit) ===")
    for volz in [0.0, 0.7]:
        for net in [1.0, 2.0]:
            slice_report(f"volz>={volz} net>={net}", volz=volz, net=net)
            slice_report(f"volz>={volz} net>={net} lvm>=-0.5",
                         volz=volz, net=net, lvm=-0.5)
            slice_report(f"volz>={volz} net>={net} acc3>=40",
                         volz=volz, net=net, acc3=40)

    print("\n=== BEST COMBOS ACROSS ALL EXIT CFGS ===")
    combos = []
    for volz in [None, 0.0, 0.7]:
        for net in [0.5, 1.0, 2.0]:
            for lvm in [-99, -1.0, -0.5]:
                idxs = [k for k, e in enumerate(events)
                        if filt(e, net=net, lvm=lvm, volz=volz)]
                if len(idxs) < 30:
                    continue
                for cfg in exits:
                    n_, wr, s = stats([out[cfg][k] for k in idxs])
                    combos.append((s, wr, n_, volz, net, lvm, cfg))
    combos.sort(reverse=True)
    for s, wr, n_, volz, net, lvm, cfg in combos[:20]:
        print(f"volz={volz} net={net} lvm={lvm} exit={cfg}: n={n_} "
              f"wr={wr:.1f}% net={s:.2f}% ${s*5:.0f}")
    print("...worst:")
    for s, wr, n_, volz, net, lvm, cfg in combos[-3:]:
        print(f"volz={volz} net={net} lvm={lvm} exit={cfg}: n={n_} "
              f"wr={wr:.1f}% net={s:.2f}% ${s*5:.0f}")


if __name__ == "__main__":
    main()
