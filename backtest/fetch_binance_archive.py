"""Download dense 1m klines from the Binance public data archive.

data.binance.vision provides full-history monthly ZIPs of 1m klines —
the standard source for long backtests. Prices on majors are near-identical
to Bitget's, so this covers the yearly-window requirement for liquid pairs.

Usage: python fetch_binance_archive.py [months] [SYM1,SYM2,...]
"""

import io
import os
import pickle
import sys
import zipfile
from datetime import datetime, timezone

import pandas as pd
import requests

BASE = "https://data.binance.vision/data/spot/monthly/klines/{sym}/1m/{sym}-1m-{ym}.zip"
BASE_DAILY = "https://data.binance.vision/data/spot/daily/klines/{sym}/1m/{sym}-1m-{ymd}.zip"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "1m_binance")

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "DOGEUSDT", "ADAUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT",
    "LTCUSDT", "DOTUSDT", "UNIUSDT", "NEARUSDT", "ATOMUSDT",
    "ALGOUSDT", "FILUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
]

COLS = ["timestamp", "open", "high", "low", "close", "volume",
        "close_time", "qv", "trades", "tbb", "tbq", "ignore"]


def month_list(n: int):
    now = datetime.now(timezone.utc)
    out = []
    y, m = now.year, now.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def fetch_symbol_months(sym: str, months: list) -> pd.DataFrame:
    frames = []
    for ym in months:
        url = BASE.format(sym=sym, ym=ym)
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 404:
                print(f"  {sym} {ym}: no data (404)", flush=True)
                continue
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                csv_name = z.namelist()[0]
                with z.open(csv_name) as fh:
                    df = pd.read_csv(fh, header=None, names=COLS)
                    frames.append(df)
            print(f"  {sym} {ym}: ok", flush=True)
        except Exception as e:
            print(f"  {sym} {ym}: {type(e).__name__} {e}", flush=True)

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    unit = "us" if ts.dropna().iloc[0] > 1e14 else "ms"
    df["timestamp"] = pd.to_datetime(ts, unit=unit, utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]].set_index(
        "timestamp"
    ).sort_index()


def fetch_symbol_days(sym: str, days: list) -> pd.DataFrame:
    frames = []
    for ymd in days:
        url = BASE_DAILY.format(sym=sym, ymd=ymd)
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                with z.open(z.namelist()[0]) as fh:
                    frames.append(pd.read_csv(fh, header=None, names=COLS))
        except Exception as e:
            print(f"  {sym} {ymd}: {type(e).__name__}", flush=True)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    unit = "us" if ts.dropna().iloc[0] > 1e14 else "ms"
    df["timestamp"] = pd.to_datetime(ts, unit=unit, utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]].set_index(
        "timestamp"
    ).sort_index()


def main():
    months_n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    symbols = sys.argv[2].split(",") if len(sys.argv) > 2 else SYMBOLS
    months = month_list(months_n)
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Binance archive: {len(symbols)} symbols x {months_n} months")

    for sym in symbols:
        out = os.path.join(DATA_DIR, f"{sym}_{months_n}m.pkl")
        if os.path.exists(out):
            print(f"{sym}: cached, skip", flush=True)
            continue
        df = fetch_symbol_months(sym, months)
        if df.empty:
            print(f"{sym}: EMPTY", flush=True)
            continue
        with open(out, "wb") as f:
            pickle.dump(df, f)
        print(f"{sym}: {len(df)} candles, {df.index[0]} -> {df.index[-1]}", flush=True)


if __name__ == "__main__":
    main()
