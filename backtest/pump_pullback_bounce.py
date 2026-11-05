#!/usr/bin/env python3
"""Pullback + bounce-confirmation entry study.

After a pump signal: wait for P% retrace from the post-signal max, then
require K consecutive non-decreasing ticks (the turn) before entering.
Skip if price runs +G% first. Same exits as before.
"""
import os
import pickle
from collections import deque

from pump_entry_study import (events_n18, dedup, simulate_exit,
                              DATA_DIR, CACHE, N)

SLOTS = 5


def pullback_bounce_entry(ps, i0, P, G, K, W=180):
    peak = ps[i0]
    for j in range(i0, min(len(ps), i0 + W)):
        p = ps[j]
        if p > peak:
            peak = p
        if p >= ps[i0] * (1 + G / 100):
            return None
        if p <= peak * (1 - P / 100):
            # retraced deep enough: now require K non-decreasing ticks
            k = j
            while k < min(len(ps), i0 + W):
                if ps[k] > peak:  # new high invalidates the dip setup
                    break
                tail = ps[k - K + 1: k + 1]
                if len(tail) == K and all(
                        tail[t] >= tail[t - 1] for t in range(1, K)) \
                        and tail[-1] > tail[0]:
                    return k
                k += 1
            return None
    return None


def main():
    with open(CACHE, "rb") as f:
        data = pickle.load(f)
    sig = {s: dedup(list(events_n18(ts, ps, vs, cs)))
           for s, (ts, ps, vs, cs) in data.items()}

    def per_event(es, label):
        tot = taken = wins = 0
        for sym, entries in es.items():
            ts, ps, vs, cs = data[sym]
            for (i0,) in entries:
                r, j = simulate_exit(ps, ts, i0)
                tot += r * 100
                taken += 1
                wins += r > 0
        print(f"{label:30s} n={taken:4d} "
              f"wr={wins/taken*100 if taken else 0:4.0f}% "
              f"net={tot:+8.1f}% (${tot*5:+8.0f})", flush=True)

    for K in (2, 3, 4):
        for P in (1.0, 1.5, 2.0, 3.0, 4.0):
            for G in (3.0, 5.0):
                es = {}
                for sym, ev in sig.items():
                    ts, ps, vs, cs = data[sym]
                    lst = []
                    for i0, _ in ev:
                        e = pullback_bounce_entry(ps, i0, P, G, K)
                        if e is not None:
                            lst.append(e)
                    if lst:
                        es[sym] = [(i,) for i in lst]
                per_event(es, f"K{K} pull{P} esc{G}")


if __name__ == "__main__":
    main()
