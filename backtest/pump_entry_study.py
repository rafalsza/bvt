#!/usr/bin/env python3
"""Pump ENTRY variants study on live-recorded ticks.

Same signal events, different entry mechanics:
  A) signal-tick entry (baseline)
  B) pullback: wait for P% retrace from post-signal max (window W ticks),
     skip if price runs +G% first
  C) micro-trigger: 6-tick window net >= T% as the entry condition
     (fires mid-spike, before the 3min window fills)

Per event we simulate the same exit (SL3/arm5/trail1/ttp1). Phase 1 =
per-event stats (deduped bursts); phase 2 = coupled sim for winners.
"""
import heapq
import os
import pickle
from collections import deque

HERE = os.path.dirname(__file__)
DATA_DIR = os.path.join(HERE, "snapshot_data_live")
CACHE = os.path.join(DATA_DIR, "parsed_live.pkl")

N = 18
FEE = 0.002
MAX_FORWARD = 3000
MAX_HOLD_SEC = 8 * 3600
SLOTS = 5
COOLOFF = 900
SL, ARM, TRAIL, TTP = 3.0, 5.0, 1.0, 1.0
BURST_GAP = 36  # ~6min dedup: one event per burst


def events_n18(ts, ps, vs, cs):
    """Loose events on the live window: rng>=3, net>=1 (no other gates)."""
    dmax, dmin = deque(), deque()
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
        if (mx - mn) / mn * 100 < 3.0:
            continue
        net = (p - ps[lo]) / ps[lo] * 100
        if net < 1.0:
            continue
        yield i, net


def micro_events(ts, ps, vs, cs, T=1.5, m=6):
    """Micro events: last m ticks net >= T% (m≈6 => ~60s)."""
    for i in range(m, len(ps)):
        net = (ps[i] - ps[i - m]) / ps[i - m] * 100
        if net >= T:
            yield i, net


def dedup(ev, gap=BURST_GAP):
    """Keep first index of each burst per (event list already sorted)."""
    out = []
    last = -gap * 2
    for i, net in ev:
        if i - last >= gap:
            out.append((i, net))
            last = i
    return out


def simulate_exit(ps, ts, i0):
    e = ps[i0]
    sl_p = e * (1 - SL / 100)
    arm_p = e * (1 + ARM / 100)
    ttp_p = e * (1 + (ARM + TTP) / 100)
    armed = False
    peak = e
    t0 = ts[i0]
    for j in range(i0 + 1, min(len(ps), i0 + MAX_FORWARD)):
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


def pullback_entry(ps, i0, P, G, W=180):
    """After signal i0: wait for P% retrace from running max (within W
    ticks). Return entry idx or None if price ran +G% first / timed out."""
    peak = ps[i0]
    for j in range(i0, min(len(ps), i0 + W)):
        p = ps[j]
        if p > peak:
            peak = p
        if p >= ps[i0] * (1 + G / 100):
            return None  # missed boat
        if p <= peak * (1 - P / 100):
            return j
    return None


def main():
    with open(CACHE, "rb") as f:
        data = pickle.load(f)
    print(f"{len(data)} symbols", flush=True)

    # ---- collect deduped events per symbol ----
    sig = {}   # sym -> [(i, net)]
    mic = {}
    for sym, (ts, ps, vs, cs) in data.items():
        sig[sym] = dedup(list(events_n18(ts, ps, vs, cs)))
        mic[sym] = dedup(list(micro_events(ts, ps, vs, cs)))
    n_sig = sum(len(v) for v in sig.values())
    n_mic = sum(len(v) for v in mic.values())
    print(f"{n_sig} N18 events, {n_mic} micro events (deduped)")

    def per_event(entry_sets, label):
        """entry_sets: sym -> list of (entry_idx, tag). Simulate each."""
        tot = taken = wins = 0
        mfes = []
        for sym, entries in entry_sets.items():
            ts, ps, vs, cs = data[sym]
            for i0, _tag in entries:
                r, j = simulate_exit(ps, ts, i0)
                # MFE
                mfe = 0.0
                for k in range(i0 + 1, j + 1):
                    d = (ps[k] - ps[i0]) / ps[i0] * 100
                    if d > mfe:
                        mfe = d
                tot += r * 100
                taken += 1
                wins += r > 0
                mfes.append(mfe)
        med = sorted(mfes)[len(mfes) // 2] if mfes else 0
        print(f"{label:28s} n={taken:4d} wr={wins/taken*100 if taken else 0:4.0f}%"
              f" net={tot:+8.1f}% (${tot*5:+8.0f}) medMFE={med:.1f}%",
              flush=True)
        return taken, wins, tot

    print("\n=== A: signal-tick entry (baseline) ===")
    per_event({s: [(i, "") for i, _ in v] for s, v in sig.items()}, "A signal tick")

    print("\n=== B: pullback entries ===")
    for P in (0.5, 1.0, 1.5, 2.0):
        for G in (3.0, 5.0, 8.0):
            es = {}
            for sym, ev in sig.items():
                ts, ps, vs, cs = data[sym]
                lst = []
                for i0, _ in ev:
                    e = pullback_entry(ps, i0, P, G)
                    if e is not None:
                        lst.append((e, ""))
                if lst:
                    es[sym] = lst
            per_event(es, f"B pull{P} esc{G}")

    print("\n=== C: micro-trigger (6-tick net) ===")
    for T in (1.0, 1.5, 2.0):
        es = {}
        for sym, (ts, ps, vs, cs) in data.items():
            evs = dedup(list(micro_events(ts, ps, vs, cs, T=T)))
            if evs:
                es[sym] = [(i, "") for i, _ in evs]
        per_event(es, f"C micro{T}%")


if __name__ == "__main__":
    main()
