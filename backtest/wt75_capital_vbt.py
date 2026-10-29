import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
from numba import njit
from vectorbt.portfolio import nb
from vectorbt.portfolio.enums import NoOrder, OrderStatus, OrderSide
import plotly.express as plotly

from wt75_vbt import wide, FEES, SLIP
from wt75_tight_vbt import metrics
from wt75_phases_vbt import PHASES, merged_data
from wt75_parameter_grid_vbt import oscillator, triggers, phase_slice

REPORT = Path(__file__).parent / 'report' / 'wt75_capital'


@njit
def order_func(c, opening, low, entries, exits, entry_idx, stops, active, audit, slots, budget):
    row = c.i // 2
    col = c.col
    price = opening[row, col]
    if c.i % 2 == 1:
        if c.position_now > 0 and low[row, col] <= stops[col]:
            return nb.close_position_nb(price=min(price, stops[col]), fees=FEES, slippage=SLIP)
        return NoOrder
    if c.position_now > 0:
        if entries[row, col]:
            audit[row, col] = 1
        if price <= stops[col] or exits[row, col] or c.i - entry_idx[col] >= 48:
            return nb.close_position_nb(price=price, fees=FEES, slippage=SLIP)
        return NoOrder
    if not entries[row, col]:
        return NoOrder
    if active[c.group] >= slots:
        audit[row, col] = 2
        return NoOrder
    if c.cash_now + 1e-8 < budget:
        audit[row, col] = 3
        return NoOrder
    audit[row, col] = 4
    amount = budget / ((1+FEES) * price * (1+SLIP))
    return nb.order_nb(size=amount, price=price, fees=FEES, slippage=SLIP, allow_partial=False)


@njit
def post_order(c, entry_idx, stops, active, audit):
    if c.order_result.status == OrderStatus.Filled:
        if c.order_result.side == OrderSide.Buy:
            entry_idx[c.col] = c.i
            stops[c.col] = c.order_result.price * .97
            active[c.group] += 1
        else:
            active[c.group] -= 1
    elif c.i % 2 == 0 and audit[c.i//2, c.col] == 4:
        audit[c.i//2, c.col] = 5


def simulate(prices, entries, exits, slots, shared=True):
    idx = entries.index
    expanded = pd.DatetimeIndex(np.repeat(idx.asi8, 2)+np.tile([0,1],len(idx)), tz=idx.tz)
    close = np.repeat(prices['close'].to_numpy(), 2, axis=0)
    close[::2] = prices['open'].to_numpy()
    close = pd.DataFrame(close, index=expanded, columns=entries.columns)
    count = entries.shape[1]
    entry_idx = np.full(count, -1, dtype=np.int64)
    stops = np.full(count, np.nan)
    active = np.zeros(count, dtype=np.int64)
    audit = np.zeros(entries.shape, dtype=np.int8)
    pf = vbt.Portfolio.from_order_func(
        close, order_func, prices['open'].to_numpy(), prices['low'].to_numpy(),
        entries.to_numpy(), exits.to_numpy(), entry_idx, stops, active, audit,
        slots if shared else 1, 2500./slots,
        post_order_func_nb=post_order, post_order_args=(entry_idx, stops, active, audit),
        init_cash=2500., cash_sharing=shared, group_by=True if shared else False)
    return pf, audit


def event_outcomes(prices, entries, exits):
    coords = np.argwhere(entries.to_numpy())
    eligible = coords[coords[:,0]+24 < len(entries)]
    labels = [f'{r}:{c}' for r,c in eligible]
    idx = pd.date_range('2000-01-01', periods=25, freq='4h', tz='UTC')
    relative = {k:pd.DataFrame(np.column_stack([f.iloc[r:r+25,c].to_numpy() for r,c in eligible]),
                              index=idx, columns=labels) for k,f in prices.items()}
    ent = pd.DataFrame(False,index=idx,columns=labels)
    ent.iloc[0] = True
    xs = pd.DataFrame(np.column_stack([exits.iloc[r:r+25,c].to_numpy() for r,c in eligible]),index=idx,columns=labels)
    xs.iloc[0] = False
    pf, _ = simulate(relative, ent, xs, 5, shared=False)
    trades = pf.trades.records_readable
    out = pd.DataFrame(eligible, columns=['row','col'],index=labels)
    closed = trades[trades.Status=='Closed'].set_index('Column')
    out['return_pct'] = closed['Return']*100
    out['symbol'] = [entries.columns[c] for r,c in eligible]
    out['entry_time'] = [str(entries.index[r]) for r,c in eligible]
    return out


def self_test():
    idx = pd.date_range('2024-01-01',periods=27,freq='4h',tz='UTC')
    cols = list('abcdef')
    p = {k:pd.DataFrame(100.,index=idx,columns=cols) for k in ['open','high','low','close']}
    ent = pd.DataFrame(False,index=idx,columns=cols)
    ent.iloc[0] = True
    xs = ent & False
    pf,a = simulate(p,ent,xs,5)
    buys = pf.orders.records_readable.query('Side == "Buy"')
    assert len(buys)==5 and (a[0]==2).sum()==1, buys
    assert pf.assets().sum(axis=1).gt(0).any()
    assert abs((buys.Size*buys.Price+buys.Fees).sum()-2500.)<1e-7
    p['low'].iloc[0,0]=90.
    pf,a = simulate(p,ent,xs,5)
    orders = pf.orders.records_readable
    assert len(orders[(orders.Column=='a') & (orders.Side=='Sell')])==1
    assert orders[(orders.Column=='a') & (orders.Side=='Sell')].iloc[0].Timestamp == idx[0]+pd.Timedelta(1,'ns')
    remaining = orders[(orders.Side=='Sell') & (orders.Column!='a')]
    assert (remaining.Timestamp==idx[24]).all()
    reference = event_outcomes(p,ent,xs)
    actual_return = pf.trades.records_readable.query('Column == "a"').iloc[0]['Return']*100
    assert abs(reference.loc['0:0','return_pct']-actual_return)<1e-8
    p['low'].iloc[0,0] = 100.
    p['open'].iloc[1,0] = 90.
    p['low'].iloc[1,0] = 90.
    gap, _ = simulate(p,ent,xs,5)
    sells = gap.orders.records_readable.query('Column == "a" and Side == "Sell"')
    assert sells.iloc[0].Timestamp == idx[1] and sells.iloc[0].Price < 90.
    print('PASS: strict5 slots, fee budgets, entry-bar SL, gap-open SL,24-bar timeout, identical counterfactual execution',flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--report-only',action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    REPORT.mkdir(parents=True,exist_ok=True)
    curves = []
    rows = []
    concentration = []
    if not args.report_only:
        data = merged_data()
        allpx = wide(data,'4h')
        valid = allpx['close'].notna()
        wt = oscillator(allpx['high'],allpx['low'],allpx['close'],10,21)
        touch = triggers(wt,valid)['touch']
        for phase,start,end in PHASES:
            prices,ent,xs = phase_slice(allpx,touch,wt,valid,'4h',start,end)
            columns = list(ent.columns[valid.loc[ent.index].any()])
            prices = {k:f[columns] for k,f in prices.items()}
            ent,xs = ent[columns],xs[columns]
            reference = event_outcomes(prices,ent,xs)
            reference.to_csv(REPORT/f'event_outcomes_{phase}.csv',index=False)
            for slots in [5,10,20]:
                for ordering in ['alphabetic','reverse']+[f'random_{seed}' for seed in range(10)]:
                    if ordering=='alphabetic':
                        order = columns
                    elif ordering=='reverse':
                        order = columns[::-1]
                    else:
                        order = list(np.random.default_rng(int(ordering.split('_')[1])).permutation(columns))
                    p = {k:f[order] for k,f in prices.items()}
                    e,x = ent[order],xs[order]
                    pf,audit = simulate(p,e,x,slots)
                    m = metrics(pf)
                    assets = pf.assets()
                    m['max_open_positions'] = int((assets>0).sum(axis=1).max())
                    assert m['max_open_positions']<=slots
                    codes = dict(occupied=1,slot_blocked=2,cash_blocked=3,accepted=4,order_rejected=5)
                    m.update({name:int((audit==code).sum()) for name,code in codes.items()})
                    matched = reference.copy()
                    remap = np.array([order.index(c) for c in columns])
                    matched['status'] = audit[matched.row.to_numpy(),remap[matched.col.to_numpy()]]
                    for label,mask in [('taken',matched.status==4),('missed',matched.status.isin([2,3,5]))]:
                        ret = matched.loc[mask,'return_pct'].dropna()
                        m[f'{label}_reference_n']=len(ret)
                        m[f'{label}_mean_return_pct']=ret.mean()
                        m[f'{label}_reference_wr']=(ret>0).mean()*100
                    rows.append(dict(phase=phase,slots=slots,ordering=ordering,**m))
                    if ordering=='alphabetic':
                        value = pf.value()
                        curves.extend(dict(phase=phase,slots=slots,time=str(ts),value=float(v)) for ts,v in value.iloc[1::2].items())
                        tr = pf.trades.records_readable
                        closed = tr[tr.Status=='Closed']
                        for dimension,groups in [('symbol',closed.groupby('Column').PnL.sum()),
                                                 ('exit_day',closed.groupby(closed['Exit Timestamp'].dt.floor('D')).PnL.sum())]:
                            best = groups.sort_values(ascending=False)
                            concentration.append(dict(phase=phase,slots=slots,dimension=dimension,
                                                       closed_net=float(closed.PnL.sum()),top5_net=float(best.head(5).sum()),
                                                       net_without_top5=float(closed.PnL.sum()-best.head(5).sum())))
                            best.rename('pnl').to_csv(REPORT/f'concentration_{phase}_{slots}_{dimension}.csv')
                        closed.to_csv(REPORT/f'trades_{phase}_{slots}.csv',index=False)
                        matched.to_csv(REPORT/f'events_audit_{phase}_{slots}.csv',index=False)
                pd.DataFrame(rows).to_csv(REPORT/'results.csv',index=False)
                print(phase,slots,'12 orderings done',flush=True)
        pd.DataFrame(curves).to_csv(REPORT/'equity.csv',index=False)
        pd.DataFrame(concentration).to_csv(REPORT/'concentration.csv',index=False)
    result = pd.read_csv(REPORT/'results.csv')
    concentration = pd.read_csv(REPORT/'concentration.csv')
    curves = pd.read_csv(REPORT/'equity.csv')
    baseline = result[result.ordering=='alphabetic']
    robustness = result.groupby(['phase','slots']).agg(min_net=('total_net','min'),median_net=('total_net','median'),
                                                       max_net=('total_net','max'),min_pf=('pf','min'),max_pf=('pf','max'),
                                                       profitable_orders=('total_net',lambda x:int((x>0).sum())))
    print('ALPHABETIC',baseline.to_string(index=False),flush=True)
    print('ORDER ROBUSTNESS',robustness.to_string(),flush=True)
    html = '<html><head><meta charset="utf-8"></head><body><h1>WT1 capital diagnosis</h1><p>Frozen4h WT10/21 touch -75, SL3%, exit WT1 crossing0 or24 bars. Bitget full available universe, user-defined hindsight phases.2500 USDT, strict caps5/10/20 positions.500/250/125 USDT are complete entry budgets INCLUDING fees/slippage; notional slightly smaller. Vectorbt from_order_func needed for strict position caps, post-fill accounting and rejection audit. Two execution steps: open and OHLC range(+1ns); entry-bar SL included. Exits and entries processed in chosen column order, no pyramiding or re-entry on same exit candle.12 fixed orderings (alphabetic/reverse/10 seeded permutations); no choosing best seed. Counterfactual missed/taken returns are independently replayed in vectorbt per event, only complete24-bar forward windows, with identical exits; overlapping, non-investable reference, not additional PnL. Occupied-symbol signals excluded from capital-missed category. Concentration based on closed PnL by exit day, not market exposure. No exchange minimum-order or liquidity model; no live deployment.</p>'
    html += '<h2>Alphabetic baseline</h2>'+baseline.round(3).to_html(index=False)
    html += '<h2>Ordering sensitivity (12 orderings per layout)</h2>'+robustness.round(3).to_html()
    html += '<h2>Concentration: removing five best symbols/days</h2>'+concentration.round(3).to_html(index=False)
    fig = plotly.line(curves,x='time',y='value',color='slots',facet_row='phase',title='Alphabetic baseline equity, independent reset each phase',height=1000)
    html += fig.to_html(full_html=False,include_plotlyjs=True)+'</body></html>'
    (REPORT/'index.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    main()
