"""Fetch historical OHLCV data from Bitget for backtesting.

Downloads 1m candles for the top-N symbols from the CoinGecko ticker
list and caches them as per-symbol pickles in backtest/data/1m/.
Supports resume: re-running skips symbols that already cover the range.

Usage: python fetch_data.py [days] [top_n] [timeframe] [tickers_file]
"""

import os
import pickle
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TICKERS_FILE = os.path.join(
    REPO_ROOT, "bitget_volatility_trading_bot", "tickerlists", "tickers_bitget_USDT.txt"
)
DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_DIR = os.path.join(DATA_ROOT, "1m")
TIMEFRAME = "1m"
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}

# Bitget history-candles caps at 200 rows; a larger limit makes ccxt request
# a wider window and silently drops everything past the first 200 -> gaps.
BATCH = 200

DAYS = 365
TOP_N = 30
MAX_WORKERS = 5
REQ_PAUSE = 0.12          # per-worker pause between requests
MAX_RETRIES = 8

_rate_lock = threading.Lock()


def load_symbols(path: str = TICKERS_FILE) -> list:
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def _make_exchange():
    return ccxt.bitget({"enableRateLimit": True})


def symbol_path(symbol: str, days: int) -> str:
    return os.path.join(DATA_DIR, f"{symbol}_{days}d.pkl")


def already_done(symbol: str, days: int, since_ms: int) -> bool:
    p = symbol_path(symbol, days)
    if not os.path.exists(p):
        return False
    try:
        df = pd.read_pickle(p)
        need_start = pd.to_datetime(since_ms, unit="ms", utc=True)
        return len(df) > 1000 and df.index[0] <= need_start + pd.Timedelta(days=2)
    except Exception:
        return False


def fetch_symbol(symbol: str, since_ms: int, end_ms: int, days: int) -> str:
    ex = _make_exchange()
    ccxt_symbol = symbol.replace("USDT", "/USDT")
    all_candles = []
    cursor = since_ms
    retries = 0

    while cursor < end_ms:
        try:
            batch = ex.fetch_ohlcv(
                ccxt_symbol, TIMEFRAME, since=cursor, limit=BATCH, params={"uta": False}
            )
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            retries += 1
            if retries > MAX_RETRIES:
                return f"{symbol}: aborted after {MAX_RETRIES} retries ({e})"
            time.sleep(min(2 * retries, 10))
            continue
        retries = 0

        if not batch:
            break
        all_candles.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cursor:
            break
        cursor = last_ts + TF_MS[TIMEFRAME]
        time.sleep(REQ_PAUSE)

    if len(all_candles) < 200:
        return f"{symbol}: only {len(all_candles)} candles, skipped"

    df = pd.DataFrame(
        all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"]
    ).drop_duplicates("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()

    with open(symbol_path(symbol, days), "wb") as f:
        pickle.dump(df, f)
    return f"{symbol}: {len(df)} candles saved"


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else DAYS
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else TOP_N
    global TIMEFRAME, DATA_DIR
    if len(sys.argv) > 3:
        TIMEFRAME = sys.argv[3]
        DATA_DIR = os.path.join(DATA_ROOT, TIMEFRAME)

    os.makedirs(DATA_DIR, exist_ok=True)
    symbols = load_symbols(sys.argv[4] if len(sys.argv) > 4 else TICKERS_FILE)[:top_n]
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms = int(
        (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
    )

    todo = [s for s in symbols if not already_done(s, days, since_ms)]
    print(
        f"Fetching {days}d of {TIMEFRAME} candles: {len(todo)} symbols to do "
        f"({len(symbols) - len(todo)} cached)",
        flush=True,
    )

    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(fetch_symbol, s, since_ms, end_ms, days): s for s in todo
        }
        for fut in as_completed(futures):
            res = fut.result()
            done += 1
            elapsed = time.time() - t0
            eta = elapsed / done * (len(todo) - done) if done else 0
            print(
                f"[{done}/{len(todo)}] {res}  ({elapsed:.0f}s, ETA {eta/60:.0f}min)",
                flush=True,
            )

    print(f"Finished in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
