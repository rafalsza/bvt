import os
import threading
import time
import requests
import yaml
from globals import user_data_path

DEFAULT_CREDS_FILE = user_data_path + "creds.yml"
# load yml file to dictionary
keys = yaml.safe_load(open(DEFAULT_CREDS_FILE))
TICKERS = "tickerlists/tickers_bitget_USDT.txt"
TIME_TO_WAIT = 360


def get_bitget():
    try:
        response = requests.get("https://api.bitget.com/api/v2/spot/public/symbols")
        dataj = response.json()["data"]

        PAIRS_WITH = "USDT"
        li = [
            item.get("symbol")
            for item in dataj
            if item["status"] == "online"
            and item["quoteCoin"] == PAIRS_WITH
        ]
        ignore = [
            "UP",
            "DOWN",
            "BEAR",
            "BULL",
            "USD",
            "BUSD",
            "EUR",
            "DAI",
            "TUSD",
            "GBP",
            "WBTC",
            "STETH",
            "CETH",
            "PAX",
            "BNSOL",
        ]
        filtered = [
            x for x in li if not (x.endswith("USD") | x.startswith(tuple(ignore)))
        ]

        # filtered = [sub[: -4] for sub in symbols]   # without USDT

        return filtered
    except requests.exceptions.RequestException as e:
        return None


def get_crypto_rank():
    url = "https://api.cryptorank.io/v2/currencies"
    headers = {"X-Api-Key": keys["cryptorank"]["api_key"]}
    params = {
        "limit": 500,  # Use one of the allowed values: 100, 500, or 1000
        "sortBy": "rank",
        "sortDirection": "ASC",
    }

    try:
        req = requests.get(url, headers=headers, params=params)
        print(f"Status code: {req.status_code}")

        if req.status_code != 200:
            print(f"Error response: {req.text}")
            return []

        data = req.json()
        if "data" not in data:
            print(f"No 'data' key in response. Keys available: {data.keys()}")
            return []

        dataj = data["data"]

        li = [item.get("symbol") for item in dataj]
        ignore_usd = [x for x in li if not (x.endswith("USD") | x.startswith("USD"))]
        list1 = ["WBTC", "UST", "USDD", "DAI", "STETH", "CETH", "GBP", "PAX"]
        filtered = [x for x in ignore_usd if all(y not in x for y in list1)]
        filtered = [x + "USDT" for x in filtered]
        return filtered

    except requests.exceptions.RequestException as e:
        print(f"Error making request to Cryptorank: {e}")
        if hasattr(e, "response") and e.response:
            print(f"Error details: {e.response.text}")
        return []
    except KeyError as e:
        print(f"Error parsing response: {e}")
        return []


def get_bitget_tickerlist():
    ticker_list = list(set(get_crypto_rank()) & set(get_bitget()))
    ticker_list.sort()
    length = len(ticker_list)

    with open(f"{TICKERS}", "w") as output:
        for item in ticker_list:
            output.write(str(item) + "\n")
    return length


def do_work():
    while True:
        try:
            if not os.path.exists(TICKERS):
                with open(TICKERS, "w") as f:
                    f.write("")

            if not threading.main_thread().is_alive():
                exit()
            print("Importing bitget tickerlist")
            get_bitget_tickerlist()
            print(
                f"Imported {TICKERS}: {get_bitget_tickerlist()} coins. Waiting {TIME_TO_WAIT} minutes for next import."
            )

            time.sleep((TIME_TO_WAIT * 60))
        except Exception as e:
            print(f"Exception do_work() import bitget tickerlist: {e}")
            continue
        except KeyboardInterrupt as ki:
            print(ki)
            exit()
