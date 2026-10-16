# Deploy na ora-1 (TEST_MODE)

## Pierwszy raz

```bash
# z lokalnego (Windows/Git Bash) - skopiuj creds (NIE sa w repo)
scp user_data/creds.yml ora-1:~/creds.yml

# na ora-1
ssh ora-1
git clone https://github.com/rafalsza/bvt.git ~/bvt
mkdir -p ~/bvt/user_data
mv ~/creds.yml ~/bvt/user_data/
cd ~/bvt
bash deploy/setup-ora1.sh
```

Skrypt: swap 4G -> build -> `docker compose up -d`.

## Operacje

```bash
docker logs -f bvt_bot                                   # logi na zywo
docker compose -f deploy/docker-compose.ora1.yml down    # stop
git -C ~/bvt pull && docker compose -f deploy/docker-compose.ora1.yml up -d --build   # update
docker stats bvt_bot                                     # RAM/CPU
```

## Stan persystentny

`user_data/` (transactions.db, coins_bought.json, creds.yml, config.yml) oraz
`bitget_volatility_trading_bot/logs/` sa mountowane z hosta - restart kontenera
nie kasuje historii.

## Limity

Kontener: max 512MB RAM / 1 CPU. Logi dockera rotowane (5 x 10MB).
Swap na hoscie: 4G.

## Uwagi

- `TEST_MODE: true` w config.yml - zlecenia sa mockowane.
- creds.yml nigdy nie trafia do obrazu (Dockerfile-bot nie COPY-uje user_data).
- Klucze API na Bitget: tylko trade, bez withdraw.
