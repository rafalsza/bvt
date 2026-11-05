#!/usr/bin/env python3
"""Window-length study for the pump detector on the live-recorded ticks.

For each window N (18/36/60/90/180 ticks ~= 3/6/10/15/30 min):
  - extract events passing the live gate stack (rng>=3%, net>=1%,
    wvol>=5000, chg24>=-10); pretrend measured over the preceding window
  - simulate SL3 / arm5 / trail1 exit per event
  - coupled sim: 5 slots, per-symbol mutex, 15min cooloff
  - report n, WR, net PnL, MFE stats, and entry lateness (net at entry)
"""
import csv
import gzip
import heapq
import os
import pickle
from array import array
from collections import deque
from datetime import datetime

HERE = os.path.dirname(__file__)
DATA_DIR = os.path.join(HERE, "snapshot_data_live")
CACHE = os.path.join(DATA_DIR, "parsed_live.pkl")

FEE = 0.002
TRADE_USDT = 500.0
MAX_FORWARD = 3000
MAX_HOLD_SEC = 8 * 3600
SLOTS = 5
COOLOFF = 900
NS = [18, 36, 60, 90, 180]
SL, ARM, TRAIL, TTP = 3.0, 5.0, 1.0, 1.0


def load_data():
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
                    ep = int(datetime.strptime(row[0][:19],
                                               "%Y-%m-%dT%H:%M:%S").timestamp())
                except ValueError:
                    continue
                d = data.get(row[1])
                if d is None:
                    d = data[row[1]] = (
                        array("i"), array("f"), array("d"), array("f"))
                d[0].append(ep)
                d[1].append(float(row[2]))
                d[2].append(float(row[3]) if row[3] else 0.0)
                d[3].append(float(row[4]) if row[4] else 0.0)
    for s in data:
        ts, ps, vs, cs = data[s]
        order = sorted(range(len(ts)), key=ts.__getitem__)
        data[s] = (array("i", [ts[i] for i in order]),
                   array("f", [ps[i] for i in order]),
                   array("d", [vs[i] for i in order]),
                   array("f", [cs[i] for i in order]))
    with open(CACHE, "wb") as f:
        pickle.dump(data, f, protocol=4)
    return data


def window_events(ts, ps, vs, cs, n):
    dmax = deque()
    dmin = deque()
    for i in range(len(ps)):
        p = ps[i]
        while dmax and ps[dmax[-1]] <= p:
            dmax.pop()
        dmax.append(i)
        while dmin and ps[dmin[-1]] >= p:
            dmin.pop()
        dmin.append(i)
        if i < 2 * n:
            continue
        lo = i - n + 1
        while dmax[0] < lo:
            dmax.popleft()
        while dmin[0] < lo:
            dmin.popleft()
        mx, mn = ps[dmax[0]], ps[dmin[0]]
        rng = (mx - mn) / mn * 100
        if rng < 3.0:
            continue
        net = (p - ps[lo]) / ps[lo] * 100
        if net < 1.0:
            continue
        # live gate stack
        wvol = vs[i] - vs[lo - 1]
        if wvol < 5000:
            continue
        c24 = cs[i]
        if c24 is not None and c24 < -10:
            continue
        plo = lo - n
        pre = (ps[lo] - ps[plo]) / ps[plo] * 100
        if pre < -1.0:
            continue
        yield i, rng, net, pre, wvol


def simulate_exit(ps, ts, i0):
    e = ps[i0]
    sl_p = e * (1 - SL / 100)
    arm_p = e * (1 + ARM / 100)
    ttp_p = e * (1 + (ARM + TTP) / 100)
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
            if p <= peak * (1 - TRAIL / 100):
                return (p / e - 1 - FEE), j
            if p >= ttp_p:
                return (p / e - 1 - FEE), j
    j = len(ps) - 1
    return (ps[j] / e - 1 - FEE), j


def coupled(events, data):
    open_until = []
    open_syms = {}
    cool = {}
    tot = taken = wins = 0
    nets = []
    for t, sym, i, rng, net, pre, wvol in events:
        if t < cool.get(sym, 0):
            continue
        while open_until and open_until[0] <= t:
            heapq.heappop(open_until)
        open_syms = {s: e for s, e in open_syms.items() if e > t}
        if len(open_until) >= SLOTS or sym in open_syms:
            continue
        r, j = simulate_exit(data[sym][1], data[sym][0], i)
        ex_t = data[sym][0][j]
        heapq.heappush(open_until, ex_t)
        open_syms[sym] = ex_t
        cool[sym] = ex_t + COOLOFF
        tot += r * 100
        taken += 1
        wins += r > 0
        nets.append(net)
    return taken, wins, tot, nets


def main():
    data = load_data()
    print(f"{len(data)} symbols", flush=True)
    for n in NS:
        events = []
        for sym, (ts, ps, vs, cs) in data.items():
            for i, rng, net, pre, wvol in window_events(ts, ps, vs, cs, n):
                events.append((ts[i], sym, i, rng, net, pre, wvol))
        events.sort()
        taken, wins, tot, nets = coupled(events, data)
        med = sorted(nets)[len(nets) // 2] if nets else 0
        print(f"N={n:3d} (~{n*10//60}min): events={len(events):5d} "
              f"taken={taken:4d} wr={wins/taken*100 if taken else 0:4.0f}% "
              f"net={tot:+8.1f}% (${tot*5:+8.0f}) med_net_at_entry={med:+.1f}%",
              flush=True)


if __name__ == "__main__":
    main()
