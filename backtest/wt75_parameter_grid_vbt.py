import argparse
import ast
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
import plotly.express as plotly

from wt75_vbt import wide, WARMUP, FEES, SLIP
from wt75_tight_vbt import adjust_sl, adjust_tp, timed_signals, turn_events, metrics
from wt75_phases_vbt import merged_data, PHASES

REPORT = Path(__file__).parent / 'report' / 'wt75_parameter_grid'
SOURCE = Path('C:/python_projects/trading-python/backtest/vectorbt-tests/wavetrend-backtest/w_params.py')


def oscillator(h, l, c, n1, n2):
    ap = (h+l+c)/3
    esa = ap.ewm(span=n1, adjust=False).mean()
    dev = (ap-esa).abs().ewm(span=n1, adjust=False).mean()
    return ((ap-esa)/(.015*dev.replace(0, np.nan))).ewm(span=n2, adjust=False).mean()


def triggers(wt, valid):
    touch = (wt < -75) & (wt.shift(1) >= -75) & (valid.cumsum() > WARMUP)
    turn = pd.DataFrame(turn_events(wt.to_numpy(), touch.to_numpy(), valid.to_numpy()),
                        index=wt.index, columns=wt.columns)
    return {'touch': touch, 'turn': turn}


def execute(prices, entries, exits, shared):
    idx = entries.index
    expanded = pd.DatetimeIndex(np.repeat(idx.asi8, 2) + np.tile([0, 1], len(idx)), tz=idx.tz)
    p = {}
    for key in prices:
        arr = np.repeat(prices[key].to_numpy(), 2, axis=0)
        if key != 'open':
            arr[::2] = prices['open'].to_numpy()
        p[key] = pd.DataFrame(arr, index=expanded, columns=entries.columns)
    ent = np.zeros((len(expanded), entries.shape[1]), dtype=np.bool_)
    xs = ent.copy()
    ent[::2] = entries.to_numpy()
    xs[::2] = exits.to_numpy()
    entry_idx = np.full(entries.shape[1], -1, dtype=np.int64)
    return vbt.Portfolio.from_signals(
        close=p['close'], open=p['open'], high=p['high'], low=p['low'], price=p['open'],
        signal_func_nb=timed_signals, signal_args=(ent, xs, entry_idx, 48),
        adjust_sl_func_nb=adjust_sl, adjust_sl_args=(entry_idx, 48),
        adjust_tp_func_nb=adjust_tp, adjust_tp_args=(48,),
        sl_stop=.03, stop_entry_price='fillprice', fees=FEES, slippage=SLIP,
        size=500., size_type='value', allow_partial=False, accumulate=False,
        init_cash=2500., cash_sharing=shared, group_by=True if shared else False, call_seq='auto')


def phase_slice(prices, event, wt, valid, tf, start, end):
    idx = wt.index
    mask = (idx >= pd.Timestamp(start, tz=idx.tz))
    if end:
        mask &= idx < pd.Timestamp(end, tz=idx.tz)
    ent = (event.mul(mask, axis=0).shift(1, fill_value=False) & valid).loc[mask]
    exits = (((wt > 0) & (wt.shift(1) <= 0)).mul(mask, axis=0).shift(1, fill_value=False) & valid).loc[mask]
    return {k:f.loc[mask].ffill().bfill() for k,f in prices.items()}, ent, exits


def column_metrics(pf):
    records = pf.trades.records_readable
    closed = records[records.Status == 'Closed']
    value = pf.value()
    net = value.iloc[-1] - 2500.
    peak = value.cummax().clip(lower=2500.)
    dd = (peak-value).max()
    result = []
    for col in value.columns:
        pnl = closed.loc[closed.Column == col, 'PnL']
        loss = -pnl[pnl < 0].sum()
        monthly = value[col].resample('MS').last().diff()
        monthly.iloc[0] = value[col].resample('MS').last().iloc[0]-2500.
        result.append(dict(column=col, n=len(pnl), pf=float(pnl[pnl > 0].sum()/loss) if loss else (np.inf if len(pnl) else 0.),
                           wr=float((pnl > 0).mean()*100), closed_net=float(pnl.sum()), total_net=float(net[col]), dd=float(dd[col]),
                           positive_months=int((monthly > 0).sum()), months=len(monthly)))
    return result


def self_test():
    idx = pd.date_range('2024-01-01', periods=28, freq='h', tz='UTC')
    prices = {k:pd.DataFrame(100., index=idx, columns=['test']) for k in ['open','high','low','close']}
    ent = pd.DataFrame(False, index=idx, columns=['test'])
    ent.iloc[1,0] = True
    empty = ent & False
    prices['low'].iloc[1,0] = 90.
    pf = execute(prices, ent, empty, False)
    orders = pf.orders.records_readable
    assert len(orders)==2 and orders.iloc[1].Timestamp == idx[1]+pd.Timedelta(1,'ns'), orders
    assert orders.iloc[1].Price < 98., orders
    prices['low'].iloc[1,0] = 100.
    pf = execute(prices, ent, empty, False)
    assert pf.orders.records_readable.iloc[1].Timestamp == idx[25]
    prices['low'].iloc[25,0] = 90.
    pf = execute(prices, ent, empty, False)
    assert pf.orders.records_readable.iloc[1].Price > 99.
    print('PASS: entry-candle SL, 24 real-bar timeout, market-open exit priority', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    REPORT.mkdir(parents=True, exist_ok=True)
    if not args.report_only:
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        saved = ast.literal_eval(tree.body[0].value)
        data = merged_data()
        common = sorted(set(data) & set(saved))
        pd.DataFrame([dict(symbol=s,n1=saved[s][0],n2=saved[s][1]) for s in common]).to_csv(REPORT/'saved_parameters.csv',index=False)
        rows = []
        grid_rows = []
        for tf in ['1h','4h']:
            prices = wide({s:data[s] for s in common}, tf)
            valid = prices['close'].notna()
            for setting in ['standard','saved']:
                wt = pd.DataFrame({s:oscillator(prices['high'][s],prices['low'][s],prices['close'][s],
                                                *(saved[s] if setting=='saved' else (10,21))) for s in common})
                for entry,event in triggers(wt,valid).items():
                    for phase,start,end in PHASES:
                        p,e,x = phase_slice(prices,event,wt,valid,tf,start,end)
                        for shared in [False,True]:
                            pf = execute(p,e,x,shared)
                            if shared:
                                result = metrics(pf)
                            else:
                                per = pd.DataFrame(column_metrics(pf))
                                per.assign(tf=tf,setting=setting,entry=entry,phase=phase).to_csv(REPORT/f'coins_{tf}_{setting}_{entry}_{phase}.csv',index=False)
                                trades = pf.trades.records_readable
                                pnl = trades.loc[trades.Status=='Closed','PnL']
                                loss = -pnl[pnl<0].sum()
                                result = metrics(pf)
                                result['pf'] = float(pnl[pnl>0].sum()/loss) if loss else 0.
                            rows.append(dict(tf=tf,setting=setting,entry=entry,phase=phase,mode='shared' if shared else 'every',symbols=len(common),**result))
                pd.DataFrame(rows).to_csv(REPORT/'saved_comparison.csv',index=False)
                print(tf,setting,'basket done',len(common),'symbols',flush=True)
            for sym in ['BTCUSDT','ETHUSDT']:
                single = wide({sym:data[sym]},tf)
                pairs = list(product(range(10,40),range(10,40)))
                for offset in range(0,len(pairs),30):
                    batch = pairs[offset:offset+30]
                    labels = [f'{n1}_{n2}' for n1,n2 in batch]
                    wt = pd.DataFrame({label:oscillator(single['high'][sym],single['low'][sym],single['close'][sym],n1,n2)
                                       for label,(n1,n2) in zip(labels,batch)})
                    p = {k:pd.DataFrame(np.repeat(f[[sym]].to_numpy(),len(batch),axis=1),index=f.index,columns=labels) for k,f in single.items()}
                    valid = p['close'].notna()
                    for entry,event in triggers(wt,valid).items():
                        for phase,start,end in PHASES:
                            pp,e,x = phase_slice(p,event,wt,valid,tf,start,end)
                            pf = execute(pp,e,x,False)
                            for r in column_metrics(pf):
                                n1,n2 = map(int,r.pop('column').split('_'))
                                grid_rows.append(dict(symbol=sym,tf=tf,entry=entry,phase=phase,n1=n1,n2=n2,**r))
                    if (offset+30)%150==0:
                        print(tf,sym,offset+30,'/900',flush=True)
                pd.DataFrame(grid_rows).to_csv(REPORT/'grid.csv',index=False)
    comparison = pd.read_csv(REPORT/'saved_comparison.csv')
    grid = pd.read_csv(REPORT/'grid.csv')
    rank = grid.groupby(['symbol','tf','entry','n1','n2']).agg(worst_pf=('pf','min'),min_trades=('n','min'),net=('total_net','sum'))
    rank['pass'] = (rank.worst_pf>=1.1)&(rank.min_trades>=30)
    rank = rank.sort_values('worst_pf',ascending=False)
    rank.to_csv(REPORT/'ranking.csv')
    print('BASKET',comparison.to_string(index=False),flush=True)
    print('GRID PASS',int(rank['pass'].sum()),'/',len(rank),flush=True)
    print(rank.head(12).to_string(),flush=True)
    html = '<html><head><meta charset="utf-8"></head><body><h1>WT parameter reuse: saved per-coin vs 10/21 and full 10..39 grid</h1><p>Bitget only. Same matched symbols for saved and standard. Fixed threshold -75, touch/first turn, SL3%, WT1 exit above zero, timeout24 real candles. Fees0.1% per side, slippage0.025%, 500 USDT orders. Shared basket2500 USDT; every mode independent2500 per coin/parameter. Two execution steps per candle: open, then OHLC range (+1ns synthetic timestamp). Entry-candle SL is checked; intrabar path remains unknown. Hindsight market phases and unknown provenance of saved settings mean all results are exploratory, not clean out-of-sample. Grid parameters are separate portfolios, never a cash-sharing pool. No volume filters, no EMA filter, no trailing.</p>'
    html += '<p>PF=0 with n=0 means no closed trades, not a losing sample. No grid setting reaches 30 closed trades in every phase: the short later phase limits evidence. Positive results with very few trades are not validated edges.</p>'
    html += '<h2>Matched basket PF, shared2500 USDT</h2>'
    html += comparison[comparison['mode']=='shared'].pivot(index=['tf','entry','setting'],columns='phase',values='pf').reindex(columns=['bull','bear','later']).round(3).to_html()
    html += '<h2>Matched basket: full results</h2>'+comparison.round(3).to_html(index=False)
    html += '<h2>Grid summary</h2>'+rank.head(50).round(3).to_html()
    for sym in ['BTCUSDT','ETHUSDT']:
        for tf in ['1h','4h']:
            selected = rank.reset_index()
            selected = selected[(selected.symbol==sym)&(selected.tf==tf)&(selected.entry=='turn')]
            fig = plotly.density_heatmap(selected,x='n1',y='n2',z='worst_pf',histfunc='avg',nbinsx=30,nbinsy=30,
                                         title=f'{sym} {tf}: first turn, worst-phase PF (check trade counts)',range_color=[0,2])
            html += fig.to_html(full_html=False,include_plotlyjs=True if '</script>' not in html else False)
    html += '<p>CSV: grid.csv, ranking.csv, saved_comparison.csv, saved_parameters.csv; per-coin results in coins_*.csv.</p></body></html>'
    (REPORT/'index.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    main()
