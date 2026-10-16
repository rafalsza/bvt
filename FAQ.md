# Frequently Asked Question

## Creds.yml default

```yaml
api_key: xxx
api_secret: xxx
passphrase: xxx   # Bitget API passphrase (required)

telegram:
  TELEGRAM_BOT_TOKEN: xxx
  TELEGRAM_CHAT_ID: 'xxx'
```

Create the API key on Bitget with **spot trade** permission only - never enable withdrawals. `creds.yml` is gitignored and must never be committed or baked into docker images.

## Errors and solutions

| Error   |   Solution |
|----------|-------------|
| `Timestamp for this request was ... ahead of the server's time` | Sync your NTP (`time.nist.gov`). On a VPS: `sudo timedatectl set-ntp true` |
| `'NoneType' object has no attribute 'encode'` | Your API key, secret or passphrase is not correct. |
| `Insufficient Funds` | Make sure you have available USDT (not locked in orders) and that `TRADE_TOTAL x TRADE_SLOTS` fits your balance. |
| `PermissionDenied` on classic account endpoints | Your account is in Unified Trading Account (UTA) mode - keep `UTA_MODE: true`. |
| Other Bitget API errors | See the [Bitget API docs](https://www.bitget.com/docs/common-doc/introduce/restful). |

## Questions and Answers

| Question   |   Answer |
|----------|-------------|
| What funds are required for PROD? | USDT matching `TRADE_TOTAL x TRADE_SLOTS` (check config). Optional: a small BGB balance (~20-30 USDT) if "pay fees with BGB" is enabled - cuts the taker fee from 0.1% to 0.08%; then set `TRADING_FEE: 0.08`. |
| Why are no trades happening in TEST_MODE? | Expected: the volatility detector needs a >=2.5% move within ~3 snapshots on a top-100 coin - rare outside volatile sessions. Lower `CHANGE_IN_PRICE` or widen the list if you want more signals. |
| Where is the state persisted? | `user_data/` - `transactions.db`, `coins_bought.json`, `config.yml`, `creds.yml`. Mount it as a volume in docker. |
