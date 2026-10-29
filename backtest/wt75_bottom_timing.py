from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px

from wt75_vbt import PERIODS, WARMUP, load, wide, wavetrend

REPORT = Path(__file__).parent / 'report' / 'wt75_bottom_timing'
HORIZON = 12


def events(data, tf, period):
    frames = wide(data, tf)
    wt, _ = wavetrend(frames['high'], frames['low'], frames['close'])
    trigger = (wt < -75) & (wt.shift(1) >= -75) & (frames['close'].notna().cumsum() > WARMUP)
    rows = []
    for sym in trigger.columns:
        low = frames['low'][sym].to_numpy()
        high = frames['high'][sym].to_numpy()
        close = frames['close'][sym].to_numpy()
        opening = frames['open'][sym].to_numpy()
        for i in np.flatnonzero(trigger[sym].to_numpy()):
            end = i + HORIZON + 1
            if end > len(low) or not np.isfinite(low[i:end]).all() or not np.isfinite(high[i:end]).all() or not np.isfinite(opening[i+1:end]).all():
                continue
            times = frames['close'].index[i:end]
            if not (times[1:] - times[:-1] == pd.Timedelta(tf)).all():
                continue
            window = low[i:end]
            lag = int(np.argmin(window))
            future_lag = int(np.argmin(window[1:])) + 1
            floor = low[i + future_lag]
            after = high[i+future_lag+1:end]
            rows.append(dict(period=period, tf=tf, symbol=sym, time=frames['close'].index[i],
                             lag=lag, future_lag=future_lag, signal_low=low[i], future_low=floor,
                             lower_later=bool(floor < low[i]),
                             future_vs_signal_low_pct=(floor/low[i]-1)*100,
                             future_vs_close_pct=(floor/close[i]-1)*100,
                             future_vs_next_open_pct=(floor/opening[i+1]-1)*100,
                             close_12_return_pct=(close[i+HORIZON]/opening[i+1]-1)*100,
                             rebound_after_low_pct=(after.max()/floor-1)*100 if len(after) else np.nan))
    return rows


def summary(group):
    return pd.Series(dict(n=len(group), lower_later_pct=group.lower_later.mean()*100,
                          median_lag=group.lag.median(), lag_12_pct=group.lag.eq(12).mean()*100,
                          median_future_vs_low_pct=group.future_vs_signal_low_pct.median(),
                          median_future_vs_next_open_pct=group.future_vs_next_open_pct.median(),
                          p10_future_vs_next_open_pct=group.future_vs_next_open_pct.quantile(.1),
                          median_close_12_return_pct=group.close_12_return_pct.median(),
                          median_rebound_pct=group.rebound_after_low_pct.median(),
                          rebound_observations=group.rebound_after_low_pct.notna().sum()))


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    rows = []
    for period, sub in PERIODS:
        data = load(sub)
        for tf in ['1h', '4h']:
            rows.extend(events(data, tf, period))
            print(period, tf, 'done', flush=True)
    raw = pd.DataFrame(rows)
    raw.to_csv(REPORT / 'events.csv', index=False)
    basket = raw.assign(scope='basket')
    btc = raw[raw.symbol == 'BTCUSDT'].assign(scope='BTC')
    combined = pd.concat([btc, basket], ignore_index=True)
    table = combined.groupby(['scope', 'tf', 'period']).apply(summary)
    table.to_csv(REPORT / 'summary.csv')
    print(table.to_string(), flush=True)
    distribution = combined.groupby(['scope', 'tf', 'period', 'lag']).size().rename('n').reset_index()
    distribution['percent'] = distribution.n / distribution.groupby(['scope', 'tf', 'period']).n.transform('sum') * 100
    fig = px.bar(distribution, x='lag', y='percent', color='period', barmode='group',
                 facet_row='scope', facet_col='tf', title='Lowest low timing: signal candle = 0, next candles = 1..12')
    fig.update_xaxes(dtick=1)
    fig.update_layout(height=850)
    html = '<html><head><meta charset="utf-8"></head><body><h1>WT1 -75: when does the low occur?</h1><p>Event study, not a portfolio backtest. Same WT settings and warmup as vectorbt studies. Signal at candle close. Compare signal candle low with the following 12 complete candles. Lag 0 means the signal candle is the first minimum in the 13-candle window; ties choose earliest candle. Events with missing future bars excluded. 12 bars = 12h on 1h, 48h on 4h. Minimum at bar 12 is right-censored: decline may continue. Post-low rebound uses only subsequent candles within the window, excludes the low candle itself; low at bar 12 has no rebound observation. No fees, no executable hindsight entry. Events can overlap and coins are correlated; current universe has survivorship bias. BTC is also included in basket.</p>'
    html += table.round(3).to_html() + fig.to_html(full_html=False, include_plotlyjs=True) + '</body></html>'
    (REPORT / 'index.html').write_text(html, encoding='utf-8')


if __name__ == '__main__':
    main()
