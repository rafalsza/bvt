#!/usr/bin/env python3
"""Follow-up combo sweep on promising single filters from pump_filter_study.

Reuses parsed_v2.pkl. Caches (events, outcomes) to speed iteration.
"""
import os
import pickle
from array import array
from pump_filter_study import load_data, window_events, simulate_exit, N

DATA_DIR = os.path.join(os.path.dirname(__file__), "snapshot_data")
EV_CACHE = os.path.join(DATA_DIR, "events_v2.pkl")
TRADE_USDT = 500.0

EXITS = [(2.0, 2.0, 0.5), (3.0, 2.0, 0.5), (3.0, 5.0, 1.0), (2.0, 3.0, 0.5)]
TTP = 1.0


def build():
    if os.path.exists(EV_CACHE):
        with open(EV_CACHE, "rb") as f:
            return pickle.load(f)
    data = load_data()
    events = []
    for sym, (ts, ps, vs, cs) in data.items():
        for ev in window_events(ts, ps, vs, cs):
            events.append((ts[ev[0]], sym) + ev)
    events.sort()
    out = {}
    for cfg in EXITS:
        sl, arm, tr = cfg
        res = array("f", [0.0]) * len(events)
        for k, e in enumerate(events):
            r, _ = simulate_exit(data[e[1]][1], data[e[1]][0], e[2], sl, arm, tr, TTP)
            res[k] = r * 100
        out[cfg] = res
        print(f"exit {cfg} done", flush=True)
    with open(EV_CACHE, "wb") as f:
        pickle.dump((events, out), f, protocol=4)
    return events, out


def stats(pnls):
    n = len(pnls)
    return n, (sum(1 for p in pnls if p > 0) / n * 100 if n else 0), sum(pnls)


def main():
    events, out = build()
    print(f"{len(events)} events")
    # idx: 0 epoch 1 sym 2 i 3 rng 4 net 5 lvm 6 tsm 7 acc3 8 pre 9 volz
    #      10 chg24 11 hour 12 wvol

    def rep(name, pred):
        idxs = [k for k, e in enumerate(events) if pred(e)]
        line = f"{name:48s} n={len(idxs):5d}"
        for cfg in EXITS:
            n_, wr, s = stats([out[cfg][k] for k in idxs])
            line += f" | {cfg}:{wr:4.0f}%/{s:8.1f}%"
        print(line)

    rep("baseline", lambda e: True)
    # window volume x hour
    for wv in [5000, 20000, 50000]:
        for hrs, hname in [(set(range(8, 16)), "8-15"), (set(range(12, 16)), "12-15")]:
            rep(f"wvol>={wv} hrs{hname}",
                lambda e, w=wv, h=hrs: e[12] >= w and e[11] in h)
    # window volume x pretrend
    for wv in [5000, 20000]:
        for pmin in [0.0, 0.5, 1.0, 2.0]:
            rep(f"wvol>={wv} pre>={pmin}",
                lambda e, w=wv, p=pmin: e[12] >= w and e[8] >= p)
    # hour x pretrend
    for pmin in [0.0, 0.5, 1.0]:
        rep(f"hrs8-15 pre>={pmin}",
            lambda e, p=pmin: e[11] in range(8, 16) and e[8] >= p)
    # exclude toxic chg24 [2,5] and hours 20-23
    rep("wvol>=5k excl chg24[2,5] excl hrs20-23",
        lambda e: e[12] >= 5000 and not (2 <= e[10] < 5) and e[11] not in range(20, 24))
    rep("wvol>=20k excl chg24[2,5] excl hrs20-23",
        lambda e: e[12] >= 20000 and not (2 <= e[10] < 5) and e[11] not in range(20, 24))
    rep("wvol>=20k hrs8-19 excl chg24[2,5]",
        lambda e: e[12] >= 20000 and e[11] in range(8, 20) and not (2 <= e[10] < 5))
    # pretrend>=2 alone was near-breakeven - combine
    for wv in [0, 5000, 20000]:
        rep(f"pre>=2 wvol>={wv} hrs8-19",
            lambda e, w=wv: e[8] >= 2 and e[12] >= w and e[11] in range(8, 20))
    # volz combined with wvol (relative + absolute volume)
    for vz in [0.0, 0.7]:
        rep(f"volz>={vz} wvol>=5000 hrs8-19",
            lambda e, v=vz: e[9] >= v and e[12] >= 5000 and e[11] in range(8, 20))


if __name__ == "__main__":
    main()
