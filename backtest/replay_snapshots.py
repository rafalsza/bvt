#!/usr/bin/env python3
"""Faithful re-simulation of the pump strategy on recorded live snapshots.

Phase 0: parse snapshot csv.gz files -> per-symbol (epoch[], price[]) arrays,
         cached to a pickle for repeat runs.
Phase 1: for every signal window (loosest gates) record the event, then for
         every (event x exit-config) simulate the forward exit on ticks.
         Entry params just filter the event set -> cheap sweep.
Phase 2: top combos re-run with global constraints: TRADE_SLOTS concurrent
         positions, per-symbol mutex + cooloff, daily loss limit, session stop.
"""
import csv
import gzip
import heapq
import os
import pickle
import sys
from array import array
from collections import deque
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "snapshot_data")
CACHE = os.path.join(DATA_DIR, "parsed.pkl")

N = 18                      # ring window size (18 x ~10s ~= 3min)
FEE = 0.002                 # round trip 0.1% x2
TRADE_USDT = 500.0
MAX_FORWARD = 3000          # ~8.3h of 10s ticks
MAX_HOLD_SEC = 8 * 3600

# ---------------- phase 0: parse ----------------

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
                if len(row) < 3 or row[0] == "ts":
                    continue
                try:
                    ep = int(datetime.strptime(row[0][:19], "%Y-%m-%dT%H:%M:%S").timestamp())
                except ValueError:
                    continue
                d = data.get(row[1])
                if d is None:
                    d = data[row[1]] = (array("i"), array("f"))
                d[0].append(ep)
                d[1].append(float(row[2]))
    for s in data:
        ts, ps = data[s]
        order = sorted(range(len(ts)), key=ts.__getitem__)
        data[s] = (array("i", [ts[i] for i in order]), array("f", [ps[i] for i in order]))
    with open(CACHE, "wb") as f:
        pickle.dump(data, f, protocol=4)
    return data


# ---------------- phase 1: events + exit outcomes ----------------

def window_events(ts, ps, min_chg=2.0, min_net=0.5):
    """Yield (idx, rng, net, lvm, tsm) for ticks passing the loosest gates."""
    dmax = deque()  # indices of decreasing prices (max front)
    dmin = deque()  # indices of increasing prices (min front)
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
        if rng < min_chg:
            continue
        net = (p - ps[lo]) / ps[lo] * 100
        if net < min_net:
            continue
        lvm = (p - mx) / mx * 100
        yield i, rng, net, lvm, i - dmax[0]


def simulate_exit(ps, ts, i0, sl, arm, trail, ttp):
    """Return (ret_frac_net, exit_idx)."""
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


def main():
    data = load_data()
    print(f"{len(data)} symbols, {sum(len(v[0]) for v in data.values())} ticks")

    # collect events (loosest entry gates)
    events = []  # (ts, sym, idx, rng, net, lvm, tsm)
    for sym, (ts, ps) in data.items():
        for i, rng, net, lvm, tsm in window_events(ts, ps):
            events.append((ts[i], sym, i, rng, net, lvm, tsm))
    events.sort()
    print(f"{len(events)} raw signal events (loose gates)")

    # exit config grid
    SLs = [1.5, 2.0, 3.0]
    ARMs = [1.5, 2.0, 3.0, 5.0]
    TRAILs = [0.5, 1.0, 1.5]
    TTP = 1.0
    exits = [(s, a, t) for s in SLs for a in ARMs for t in TRAILs]

    # per (event, exit_cfg) outcome - but dedupe per symbol per config first
    # to keep it sane: simulate each event once per exit cfg
    out = {}  # exit_cfg -> array of pnl aligned with events
    for cfg in exits:
        res = array("f", [0.0]) * len(events)
        out[cfg] = res
    for cfg in exits:
        sl, arm, tr = cfg
        res = out[cfg]
        for k, (t, sym, i, *_f) in enumerate(events):
            r, j = simulate_exit(data[sym][1], data[sym][0], i, sl, arm, tr, TTP)
            res[k] = r * 100
        print(f"exit cfg {cfg} done", flush=True)

    # entry gate sweep on precomputed outcomes
    CHGs = [2.0, 2.5, 3.0, 3.5, 4.0]
    NETs = [1.0, 1.5, 2.0, 2.5]
    LVMs = [-0.3, -0.5, -1.0, -1.5]
    print("\n=== PHASE 1: every signal taken, no global constraints ===")
    print("chg  net  lvm | sl  arm  tr |  n    win%   net%sum   net$")
    results = []
    for chg in CHGs:
        for net in NETs:
            for lvm in LVMs:
                idxs = [k for k, e in enumerate(events)
                        if e[3] >= chg and e[4] >= net and e[5] >= lvm]
                if not idxs:
                    continue
                for cfg in exits:
                    res = out[cfg]
                    pnls = [res[k] for k in idxs]
                    netpct = sum(pnls)
                    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
                    results.append((netpct, wr, len(idxs), chg, net, lvm, cfg))
    results.sort(reverse=True)
    for netpct, wr, n, chg, net, lvm, cfg in results[:25]:
        print(f"{chg:.1f} {net:4.1f} {lvm:5.1f} | {cfg[0]:.1f} {cfg[1]:.1f} {cfg[2]:.1f} | "
              f"{n:4d} {wr:5.1f} {netpct:9.2f} {netpct*TRADE_USDT/100:9.2f}")
    print("...worst:")
    for netpct, wr, n, chg, net, lvm, cfg in results[-5:]:
        print(f"{chg:.1f} {net:4.1f} {lvm:5.1f} | {cfg[0]:.1f} {cfg[1]:.1f} {cfg[2]:.1f} | "
              f"{n:4d} {wr:5.1f} {netpct:9.2f} {netpct*TRADE_USDT/100:9.2f}")
    # current live config for reference
    cur = [r for r in results if r[3]==2.5 and r[4]==1.0 and r[5]==-1.5 and r[6]==(3.0,5.0,1.0)]
    if cur:
        print(f"\ncurrent live cfg (2.5/1.0/-1.5, SL3 arm5 tr1): n={cur[0][2]} "
              f"wr={cur[0][1]:.1f}% net={cur[0][0]:.2f}% (${cur[0][0]*5:.0f})")

    # ---- phase 2: coupled sim for top-15 + current ----
    print("\n=== PHASE 2: slots=10, per-symbol mutex, 15min cooloff, 3-loss/day limit ===")
    top = results[:15]
    if cur:
        top.append(cur[0])
    SLOTS = 10
    COOLOFF = 900
    for netpct, wr, n, chg, net, lvm, cfg in top:
        sl, arm, tr = cfg
        open_until = []          # heap of exit epochs
        open_syms = {}           # sym -> exit epoch
        cool = {}                # sym -> allowed-after epoch
        losses = {}              # (sym, day) -> count
        tot = 0.0
        taken = 0
        for t, sym, i, rng, netv, lvmv, tsm in events:
            if rng < chg or netv < net or lvmv < lvm:
                continue
            day = t // 86400
            if losses.get((sym, day), 0) >= 3:
                continue
            if t < cool.get(sym, 0):
                continue
            while open_until and open_until[0] <= t:
                heapq.heappop(open_until)
            open_syms = {s: e for s, e in open_syms.items() if e > t}
            if len(open_until) >= SLOTS or sym in open_syms:
                continue
            r, j = simulate_exit(data[sym][1], data[sym][0], i, sl, arm, tr, TTP)
            ex_t = data[sym][0][j]
            heapq.heappush(open_until, ex_t)
            open_syms[sym] = ex_t
            cool[sym] = ex_t + COOLOFF
            if r <= 0:
                losses[(sym, day)] = losses.get((sym, day), 0) + 1
            tot += r * 100
            taken += 1
        print(f"chg{chg} net{net} lvm{lvm} exit{cfg}: taken={taken} net%={tot:.2f} "
              f"net$={tot*TRADE_USDT/100:.2f}")


if __name__ == "__main__":
    main()
