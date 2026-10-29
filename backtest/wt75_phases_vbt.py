from pathlib import Path
from itertools import product
import argparse

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from wt75_vbt import PERIODS, load, wavetrend
from wt75_tight_vbt import study_signals, portfolio, metrics

REPORT = Path(__file__).parent / 'report' / 'wt75_phases'
PHASES = [('bull', '2022-11-20', '2025-10-06'),
          ('bear', '2025-10-06', '2026-07-02'),
          ('later', '2026-07-02', None)]


def merged_data():
    parts = {}
    conflicts = 0
    for _, sub in PERIODS:
        for sym, frame in load(sub).items():
            parts.setdefault(sym, []).append(frame)
    data = {}
    for sym, frames in parts.items():
        joined = pd.concat(frames).sort_index(kind='stable')
        duplicates = joined.index.duplicated(keep=False)
        if duplicates.any():
            conflicts += int((joined.loc[duplicates].groupby(level=0)[['open', 'high', 'low', 'close']].nunique() > 1).any(axis=1).sum())
        data[sym] = joined.loc[~joined.index.duplicated(keep='last')]
    print('Merged symbols:', len(data), 'conflicting overlapping OHLC rows:', conflicts, flush=True)
    return data


def phase_frames(px, trig, has, wt, tf, start, end):
    idx = has.index
    start = pd.Timestamp(start, tz=idx.tz)
    end = pd.Timestamp(end, tz=idx.tz) if end else idx[-1] + pd.Timedelta(tf)
    mask = (idx >= start) & (idx < end)
    prices = {k: f.loc[mask] for k, f in px.items()}
    events = {k: (v.mul(mask, axis=0).shift(1, fill_value=False) & has).loc[mask]
              for k, v in trig.items() if k in ['touch', 'up', 'turn']}
    zero = ((wt > 0) & (wt.shift(1) <= 0)).mul(mask, axis=0).shift(1, fill_value=False) & has
    return prices, events, zero.loc[mask], has.loc[mask]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    data = merged_data()
    rows = []
    charts = []
    coverage = []
    for tf in ['1h', '4h']:
        px, trig, _, _, has = study_signals(data, tf)
        wt, _ = wavetrend(px['high'], px['low'], px['close'])
        for phase, start, end in PHASES:
            prices, events, zero, valid = phase_frames(px, trig, has, wt, tf, start, end)
            cols_all = list(valid.columns[valid.any(axis=0)])
            coverage.append(dict(phase=phase, tf=tf, start=str(valid.index[0]), end=str(valid.index[-1]),
                                 symbols=len(cols_all), bars=len(valid)))
            if not args.report_only:
                for scope in ['btc', 'basket']:
                    cols = ['BTCUSDT'] if scope == 'btc' else cols_all
                    p = {k: f[cols] for k, f in prices.items()}
                    for entry, sl, exit_name in product(['touch', 'up', 'turn'], [.01, .02, .03], ['r1.5', 'r2', 'wt0']):
                        ent = events[entry][cols]
                        xs = zero[cols] if exit_name == 'wt0' else ent & False
                        tp = np.nan if exit_name == 'wt0' else sl * (1.5 if exit_name == 'r1.5' else 2.)
                        for shared in ([True] if scope == 'btc' else [False, True]):
                            pf = portfolio(p, ent, xs, sl, tp, shared)
                            rows.append(dict(phase=phase, tf=tf, scope=scope, entry=entry, sl=sl, exit=exit_name,
                                             mode='shared' if shared else 'every', **metrics(pf)))
                pd.DataFrame(rows).to_csv(REPORT / 'results.csv', index=False)
                print(tf, phase, 'done', flush=True)
            if phase == 'bear':
                s = 'BTCUSDT'
                p = {k: f[[s]] for k, f in prices.items()}
                ent = events['turn'][[s]]
                pf = portfolio(p, ent, zero[[s]], .03, np.nan, True)
                title = f'BTC {tf}, BEAR 2025-10-06 through 2026-07-01 | first turn | SL3%, WT0, max24 bars'
                fig = go.Figure(go.Candlestick(x=valid.index, open=p['open'][s], high=p['high'][s],
                                              low=p['low'][s], close=p['close'][s], name='BTC'))
                orders = pf.orders.records_readable
                for side, symbol, color in [('Buy', 'triangle-up', 'green'), ('Sell', 'triangle-down', 'red')]:
                    selected = orders[orders.Side == side]
                    fig.add_trace(go.Scatter(x=selected.Timestamp, y=selected.Price, mode='markers', name=side,
                                             marker=dict(symbol=symbol, color=color, size=11)))
                fig.update_layout(title=title, xaxis_rangeslider_visible=False)
                charts.append(fig.to_html(full_html=False, include_plotlyjs=not charts))
                fig = pf.plot(subplots=['value', 'drawdowns'])
                fig.update_layout(title=title, height=800)
                charts.append(fig.to_html(full_html=False, include_plotlyjs=False))
    results = pd.read_csv(REPORT / 'results.csv')
    coverage = pd.DataFrame(coverage)
    coverage.to_csv(REPORT / 'coverage.csv', index=False)
    fixed = results[(results.sl == .03) & (results['exit'] == 'wt0')]
    table = fixed.pivot(index=['scope', 'tf', 'mode', 'entry'], columns='phase', values='pf')
    print('FIXED SL3 WT0 PF:', table.round(3).to_string(), flush=True)
    ranking = results.groupby(['scope', 'tf', 'mode', 'entry', 'sl', 'exit']).agg(
        worst_pf=('pf', 'min'), min_trades=('n', 'min'), total_net=('total_net', 'sum'))
    ranking['pass'] = (ranking.worst_pf >= 1.1) & (ranking.min_trades >= 30)
    ranking.sort_values('worst_pf', ascending=False).to_csv(REPORT / 'ranking.csv')
    print('PASS all three phases:', int(ranking['pass'].sum()), '/', len(ranking), flush=True)
    html = '<html><head><meta charset="utf-8"></head><body><h1>WT1 -75: user-defined market phases</h1><p>Bull: 2022-11-20 through 2025-10-05 inclusive. Bear: 2025-10-06 through 2026-07-01 inclusive. Later: 2026-07-02 through available data. UTC candle dates. 27 unchanged entry/exit configurations per timeframe: touch/up/first turn, SL1/2/3%, TP1.5R/2R or WT1 crossing zero, max24 bars. History merged and indicators warmed before phase start; capital resets flat per phase, signals from before phase excluded. Open positions marked at final close, not forcibly liquidated. Fees0.1%/side and slippage0.025%, shared2500 USDT, fixed500 orders. Entry-candle stops not checked by from_signals: approximation, especially for tight stops. Known hindsight phase labels, not a tradable regime filter. Current surviving universe, correlated coins, and unequal phase lengths limit interpretation.</p>'
    html += '<h2>Data coverage</h2>' + coverage.to_html(index=False)
    html += '<h2>Matched comparison: SL3%, WT1 exit above zero, max24 bars (PF)</h2>' + table.round(3).to_html()
    html += '<h2>All results</h2>' + results.round(3).to_html(index=False) + ''.join(charts) + '</body></html>'
    (REPORT / 'index.html').write_text(html, encoding='utf-8')


if __name__ == '__main__':
    main()
