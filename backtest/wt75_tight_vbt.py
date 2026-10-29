from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd
import vectorbt as vbt
from numba import njit

from wt75_vbt import FEES, SLIP, PERIODS, load, signals, wavetrend
from wt75_variants_vbt import metrics

REPORT = Path(__file__).parent / 'report' / 'wt75_tight'


@njit
def adjust_sl(c, entry_idx, max_bars):
    entry_idx[c.col] = c.init_i
    if c.position_now > 0 and c.i - c.init_i >= max_bars:
        return np.nan, False
    return c.curr_stop, c.curr_trail


@njit
def adjust_tp(c, max_bars):
    if c.position_now > 0 and c.i - c.init_i >= max_bars:
        return np.nan
    return c.curr_stop


@njit
def timed_signals(c, entries, exits, entry_idx, max_bars):
    if c.position_now > 0:
        return False, exits[c.i, c.col] or c.i - entry_idx[c.col] >= max_bars, False, False
    return entries[c.i, c.col], False, False, False


def portfolio(px, entries, exits, sl, tp, shared, max_bars=24):
    entry_idx = np.full(entries.shape[1], -1, dtype=np.int64)
    return vbt.Portfolio.from_signals(
        close=px['close'], price=px['open'], open=px['open'], high=px['high'], low=px['low'],
        signal_func_nb=timed_signals,
        signal_args=(entries.to_numpy(), exits.to_numpy(), entry_idx, max_bars),
        adjust_sl_func_nb=adjust_sl, adjust_sl_args=(entry_idx, max_bars),
        adjust_tp_func_nb=adjust_tp, adjust_tp_args=(max_bars,),
        sl_stop=sl, tp_stop=tp, stop_entry_price='fillprice', fees=FEES, slippage=SLIP,
        size=500., size_type='value', allow_partial=False, accumulate=False,
        init_cash=2500. if shared else 1e9, cash_sharing=shared,
        group_by=True if shared else False, call_seq='auto')


def self_test():
    idx = pd.date_range('2024-01-01', periods=35, freq='h')
    px = {k: pd.DataFrame(100., index=idx, columns=['test']) for k in ['open', 'high', 'low', 'close']}
    ent = pd.DataFrame(False, index=idx, columns=['test'])
    ent.iloc[[1, 4, 27], 0] = True
    empty = ent & False
    pf = portfolio(px, ent, empty, .02, .04, True)
    orders = pf.orders.records_readable
    assert list(orders.Timestamp) == [idx[1], idx[25], idx[27]], orders
    px['low'].iloc[2, 0] = 95.
    pf = portfolio(px, ent, empty, .02, .04, True)
    orders = pf.orders.records_readable
    assert orders.iloc[1].Timestamp == idx[2], orders
    assert orders.iloc[2].Timestamp == idx[4], orders
    px['low'].iloc[2, 0] = 100.
    px['low'].iloc[25, 0] = 90.
    pf = portfolio(px, ent, empty, .02, .04, True)
    assert pf.orders.records_readable.iloc[1].Price > 99., pf.orders.records_readable
    print('PASS: timeout from executed entry, stop, re-entry, timeout-open priority', flush=True)


@njit
def turn_events(wt, touch, valid):
    out = np.zeros(wt.shape, dtype=np.bool_)
    for col in range(wt.shape[1]):
        armed = False
        for i in range(1, wt.shape[0]):
            if not valid[i, col] or not valid[i-1, col]:
                armed = False
            elif touch[i, col]:
                armed = True
            elif armed and wt[i, col] > wt[i-1, col]:
                out[i, col] = True
                armed = False
    return out


def study_signals(data, tf):
    px, trig, flt, xs, has = signals(data, tf)
    wt, _ = wavetrend(px['high'], px['low'], px['close'])
    trig['turn'] = pd.DataFrame(turn_events(wt.to_numpy(), trig['touch'].to_numpy(), has.to_numpy()),
                                index=has.index, columns=has.columns)
    return px, trig, flt, xs, has


def main():
    global REPORT
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--report-only', action='store_true')
    parser.add_argument('--turn', action='store_true')
    args = parser.parse_args()
    if args.turn:
        REPORT = REPORT.with_name('wt75_turn')
    if args.self_test:
        self_test()
        return
    REPORT.mkdir(parents=True, exist_ok=True)
    rows = []
    for period, sub in ([] if args.report_only else PERIODS):
        data = load(sub)
        for tf in ['1h', '4h']:
            px, trig, _, _, has = study_signals(data, tf)
            wt, _ = wavetrend(px['high'], px['low'], px['close'])
            zero = ((wt > 0) & (wt.shift(1) <= 0)).shift(1, fill_value=False) & has
            for scope in ['btc', 'basket']:
                cols = ['BTCUSDT'] if scope == 'btc' else list(has.columns)
                prices = {k: f[cols] for k, f in px.items()}
                for entry, sl, exit_name in product(['turn'] if args.turn else ['touch', 'up'], [.01, .02, .03], ['r1.5', 'r2', 'wt0']):
                    ent = (trig[entry].shift(1, fill_value=False) & has)[cols]
                    exits = zero[cols] if exit_name == 'wt0' else ent & False
                    tp = np.nan if exit_name == 'wt0' else sl * (1.5 if exit_name == 'r1.5' else 2.)
                    for shared in ([True] if scope == 'btc' else [False, True]):
                        pf = portfolio(prices, ent, exits, sl, tp, shared)
                        rows.append(dict(period=period, tf=tf, scope=scope, entry=entry, sl=sl, exit=exit_name,
                                         mode='shared' if shared else 'every', **metrics(pf)))
            pd.DataFrame(rows).to_csv(REPORT / 'results.csv', index=False)
            print(period, tf, 'done', flush=True)
    results = pd.read_csv(REPORT / 'results.csv')
    keys = ['scope', 'tf', 'entry', 'sl', 'exit', 'mode']
    ranked = results.groupby(keys).agg(worst_pf=('pf', 'min'), min_trades=('n', 'min'), net=('total_net', 'sum'))
    ranked['pass'] = (ranked.worst_pf >= 1.1) & (ranked.min_trades >= 30)
    ranked = ranked.sort_values('worst_pf', ascending=False)
    ranked.to_csv(REPORT / 'ranking.csv')
    print(ranked.head(15).to_string(), flush=True)
    print('PASS', int(ranked['pass'].sum()), '/', len(ranked), flush=True)
    charts = []
    data = load('1h')
    import plotly.graph_objects as go
    for tf in ['1h', '4h']:
        candidates = ranked.loc[('btc', tf)]
        entry, sl, exit_name, mode = candidates.index[0]
        px, trig, _, _, has = study_signals({'BTCUSDT': data['BTCUSDT']}, tf)
        wt, _ = wavetrend(px['high'], px['low'], px['close'])
        ent = trig[entry].shift(1, fill_value=False) & has
        exits = ((wt > 0) & (wt.shift(1) <= 0)).shift(1, fill_value=False) & has if exit_name == 'wt0' else ent & False
        tp = np.nan if exit_name == 'wt0' else sl * (1.5 if exit_name == 'r1.5' else 2.)
        pf = portfolio(px, ent, exits, sl, tp, True)
        title = f'BTC {tf}: {entry}, SL {sl:.0%}, {exit_name}, max 24 bars (selected post-hoc)'
        fig = go.Figure(go.Candlestick(x=has.index, open=px['open']['BTCUSDT'], high=px['high']['BTCUSDT'],
                                      low=px['low']['BTCUSDT'], close=px['close']['BTCUSDT'], name='BTC'))
        orders = pf.orders.records_readable
        for side, symbol, color in [('Buy', 'triangle-up', 'green'), ('Sell', 'triangle-down', 'red')]:
            selected = orders[orders.Side == side]
            fig.add_trace(go.Scatter(x=selected.Timestamp, y=selected.Price, mode='markers', name=side,
                                     marker=dict(symbol=symbol, color=color, size=11)))
        fig.update_layout(title=title, xaxis_rangeslider_visible=False)
        charts.append(fig.to_html(full_html=False, include_plotlyjs=not charts))
        if args.turn:
            osc_fig = go.Figure(go.Scatter(x=wt.index, y=wt['BTCUSDT'], name='WT1'))
            mask = trig['turn']['BTCUSDT']
            osc_fig.add_trace(go.Scatter(x=wt.index[mask], y=wt['BTCUSDT'][mask], mode='markers',
                                        name='First turn signal (close)', marker=dict(color='orange', size=9)))
            osc_fig.add_hline(y=-75, line_dash='dash')
            osc_fig.add_hline(y=0, line_dash='dash')
            osc_fig.update_layout(title=f'BTC {tf}: WT1 and all first-turn signals')
            charts.append(osc_fig.to_html(full_html=False, include_plotlyjs=False))
        fig = pf.plot(subplots=['value', 'drawdowns'])
        fig.update_layout(title=title, height=850)
        charts.append(fig.to_html(full_html=False, include_plotlyjs=False))
    html = '<html><head><meta charset="utf-8"></head><body><h1>WT1 -75: tight stops</h1><p>18 configurations per timeframe. SL 1/2/3%, TP 1.5R/2R or WT1 crossing above zero. All have timeout at open 24 bars after actual entry (24h on 1h, 96h on 4h). Fees 0.1% per side, slippage 0.025%. Fill-price stops, next-open signals. Same-bar stops are not checked on entry bar by from_signals; OHLC ambiguity remains. Shared 2500 USDT includes fees, fixed 500 USDT orders; not strict five slots. All periods previously seen: exploratory comparison, not clean out-of-sample.</p>'
    if args.turn:
        html = html.replace('18 configurations per timeframe.', 'First WT1 increase after -75: one signal per crossing, no expiry before first increase. 9 exit configurations per timeframe.')
        baseline = pd.read_csv(REPORT.with_name('wt75_tight') / 'results.csv')
        comparison = pd.concat([baseline, results], ignore_index=True)
        comparison.to_csv(REPORT / 'comparison.csv', index=False)
        matched = comparison[(comparison.scope == 'basket') & (comparison.sl == .03) & (comparison['exit'] == 'wt0')]
        html += '<h2>Matched PF comparison: basket, SL3%, WT1 exit above zero, 24 bars</h2>'
        html += matched.pivot(index=['tf', 'mode', 'entry'], columns='period', values='pf').round(3).to_html()
        html += '<h2>All results including previous touch/up study</h2>' + comparison.to_html(index=False)
    html += ranked.to_html() + results.to_html(index=False) + ''.join(charts) + '</body></html>'
    (REPORT / 'index.html').write_text(html, encoding='utf-8')


if __name__ == '__main__':
    main()
