import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt

from wt75_vbt import FEES, SLIP, PERIODS, WARMUP, load, signals

ENTRIES = ['touch', 'up', 'cross', 'div', 'div_break']
EXITS = ['ob60', 'xdn0', 'fixed5', 'r2', 'r3']
REPORT = Path(__file__).parent / 'report' / 'wt75_variants'


def prepare(data, tf):
    from wt75_vbt import wavetrend
    px, trig, _, xs, has = signals(data, tf)
    wt, _ = wavetrend(px['high'], px['low'], px['close'])
    events = {k: pd.DataFrame(False, index=has.index, columns=has.columns) for k in ENTRIES}
    floors = {k: pd.DataFrame(np.nan, index=has.index, columns=has.columns) for k in ENTRIES}
    for col, sym in enumerate(has.columns):
        lo = px['low'][sym].to_numpy()
        hi = px['high'][sym].to_numpy()
        close = px['close'][sym].to_numpy()
        osc = wt[sym].to_numpy()
        valid = has[sym].to_numpy()
        piv = pd.Series(lo).eq(pd.Series(lo).rolling(7, center=True).min()).to_numpy()
        prev = None
        pending = None
        floor = np.nan
        count = 0
        for t in range(len(lo)):
            if not valid[t]:
                continue
            count += 1
            if trig['touch'].iat[t, col]:
                floor = lo[t]
            elif np.isfinite(floor):
                floor = min(floor, lo[t])
            for k in ['touch', 'up', 'cross']:
                if trig[k].iat[t, col] and np.isfinite(floor):
                    events[k].iat[t, col] = True
                    floors[k].iat[t, col] = floor * .998
            j = t - 3
            if j >= 3 and piv[j] and valid[j-3:t+1].all():
                if prev is not None and count > WARMUP:
                    i = prev
                    if lo[j] < lo[i] and osc[j] > osc[i] and osc[i] <= -75:
                        events['div'].iat[t, col] = True
                        floors['div'].iat[t, col] = floor * .998
                        pending = (hi[i:j+1].max(), lo[j], floor * .998)
                prev = j
            if pending is not None:
                level, bottom, stop = pending
                if lo[t] < bottom:
                    pending = None
                elif close[t] > level:
                    events['div_break'].iat[t, col] = True
                    floors['div_break'].iat[t, col] = min(stop, lo[t] * .998)
                    pending = None
    return px, events, floors, xs, has


def portfolio(px, event, floor, xs, has, exit_name, shared):
    ent = event.shift(1, fill_value=False) & has
    stop_price = floor.shift(1)
    risk = (px['open'] - stop_price) / px['open']
    if exit_name in ['r2', 'r3']:
        ent &= risk.gt(0) & risk.lt(1)
        sl = risk.where(ent, .1)
        tp = sl * (2 if exit_name == 'r2' else 3)
    else:
        sl = .05 if exit_name == 'fixed5' else .1
        tp = .05 if exit_name == 'fixed5' else np.nan
    exits = xs.get(exit_name, pd.DataFrame(False, index=has.index, columns=has.columns))
    exits = exits.shift(1, fill_value=False) & has
    return vbt.Portfolio.from_signals(
        close=px['close'], price=px['open'], open=px['open'], high=px['high'], low=px['low'],
        entries=ent, exits=exits, sl_stop=sl, tp_stop=tp, stop_entry_price='fillprice',
        fees=FEES, slippage=SLIP, size=500., size_type='value', allow_partial=False,
        accumulate=False, init_cash=2500. if shared else 1e9,
        cash_sharing=shared, group_by=True if shared else False, call_seq='auto')


def metrics(pf):
    trades = pf.trades.records_readable
    closed = trades[trades.Status == 'Closed']
    pnl = closed.PnL
    loss = -pnl[pnl < 0].sum()
    value = pf.value()
    if isinstance(value, pd.DataFrame):
        value = value.sum(axis=1)
    initial = float(np.asarray(pf.init_cash).sum())
    curve = np.r_[initial, value.to_numpy()]
    monthly = value.resample('MS').last().diff()
    monthly.iloc[0] = value.resample('MS').last().iloc[0] - initial
    return dict(n=len(closed), pf=float(pnl[pnl > 0].sum()/loss) if loss else (np.inf if len(closed) else 0),
                wr=float((pnl > 0).mean()*100), closed_net=float(pnl.sum()),
                total_net=float(value.iloc[-1]-initial), dd=float((np.maximum.accumulate(curve)-curve).max()),
                positive_months=int((monthly > 0).sum()), months=len(monthly),
                open_positions=int((trades.Status == 'Open').sum()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--btc-only', action='store_true')
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    rows = pd.read_csv(REPORT / 'results.csv').to_dict('records') if args.report_only else []
    for period, sub in ([] if args.report_only else PERIODS):
        data = load(sub)
        if args.btc_only:
            data = {'BTCUSDT': data['BTCUSDT']}
        for tf in ['1h', '4h']:
            px, events, floors, xs, has = prepare(data, tf)
            for scope in (['btc'] if args.btc_only else ['btc', 'basket']):
                cols = ['BTCUSDT'] if scope == 'btc' else list(has.columns)
                prices = {k: f[cols] for k, f in px.items()}
                for entry in ENTRIES:
                    for exit_name in EXITS:
                        for shared in ([True] if scope == 'btc' else [False, True]):
                            pf = portfolio(prices, events[entry][cols], floors[entry][cols],
                                           {k: f[cols] for k, f in xs.items()}, has[cols], exit_name, shared)
                            rows.append(dict(period=period, tf=tf, scope=scope, entry=entry, exit=exit_name,
                                             mode='shared' if shared else 'every', **metrics(pf)))
            pd.DataFrame(rows).to_csv(REPORT / 'results.csv', index=False)
            print(period, tf, 'done', flush=True)
    results = pd.DataFrame(rows)
    ranked = results.groupby(['scope', 'tf', 'entry', 'exit', 'mode']).agg(
        worst_pf=('pf', 'min'), min_trades=('n', 'min'), net=('total_net', 'sum'))
    ranked['pass'] = (ranked.worst_pf >= 1.1) & (ranked.min_trades >= 30)
    ranked = ranked.sort_values('worst_pf', ascending=False)
    ranked.to_csv(REPORT / 'ranking.csv')
    print(ranked.head(12).to_string(), flush=True)
    print('PASS rows:', int(ranked['pass'].sum()), '/', len(ranked), flush=True)
    charts = []
    btc = ranked.loc['btc'].sort_values('worst_pf', ascending=False)
    data = load('1h')
    for tf in ['1h', '4h']:
        choice = btc.loc[tf].index[0]
        entry, exit_name, mode = choice
        px, events, floors, xs, has = prepare({'BTCUSDT': data['BTCUSDT']}, tf)
        pf = portfolio(px, events[entry], floors[entry], xs, has, exit_name, True)
        fig = pf.plot(subplots=['value', 'drawdowns'])
        orders = pf.orders.records_readable
        import plotly.graph_objects as go
        trade_fig = go.Figure(go.Candlestick(x=px['close'].index, open=px['open']['BTCUSDT'],
                                            high=px['high']['BTCUSDT'], low=px['low']['BTCUSDT'],
                                            close=px['close']['BTCUSDT'], name='BTC'))
        for side, marker, color in [('Buy', 'triangle-up', 'green'), ('Sell', 'triangle-down', 'red')]:
            selected = orders[orders.Side == side]
            trade_fig.add_trace(go.Scatter(x=selected.Timestamp, y=selected.Price, mode='markers',
                                           name=side, marker=dict(symbol=marker, size=12, color=color)))
        trade_fig.update_layout(title=f'BTC {tf} | {entry} / {exit_name} | executions', xaxis_rangeslider_visible=False)
        charts.append(trade_fig.to_html(full_html=False, include_plotlyjs=True))
        fig.update_layout(title=f'BTC {tf} | {entry} / {exit_name} | selected post-hoc | 2025-26', height=1100)
        charts.append(fig.to_html(full_html=False, include_plotlyjs=True))
    html = '<html><head><meta charset="utf-8"></head><body><h1>WT1 -75: vectorbt variants</h1><p>Exploratory, all periods previously seen. Fees 0.1%/side, slippage 0.025%. Signals at close, orders next open. Pivot confirmation +3 bars. Fixed 500 USDT orders; shared cash 2500 USDT including fees (not a strict five-slot rule). R targets estimated from next open; stops anchored to fill price. Monthly results and drawdown use marked-to-market equity.</p>'
    html += ranked.to_html() + results.to_html(index=False) + ''.join(charts) + '</body></html>'
    (REPORT / 'index.html').write_text(html, encoding='utf-8')


if __name__ == '__main__':
    main()
