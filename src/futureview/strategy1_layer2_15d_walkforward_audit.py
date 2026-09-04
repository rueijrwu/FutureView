from __future__ import annotations

import os
import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_entry_exit_cq_compare import build_cq
from .strategy1_exit_window_cq_audit import classify_causal
from .strategy1_layer2_price_distribution import PriceDistributionData, W, MODEL_HISTORY, HORIZON
from .strategy1_layer2_probability_calibration_audit import build_samples
from .strategy1_layer2_loss_competition_audit import train

TICKER=os.environ.get('FUTUREVIEW_TICKER','TSLA')
DATA_PERIOD=os.environ.get('FUTUREVIEW_DATA_PERIOD','8y')
ROLL_DAYS=int(os.environ.get('FUTUREVIEW_ROLL_DAYS','15'))
MEMORIES=tuple(int(x) for x in os.environ.get('FUTUREVIEW_TRAIN_MEMORIES','100,150,200').split(','))
PURGE_DAYS=int(os.environ.get('FUTUREVIEW_PURGE_DAYS','3'))
OUTPUT=os.environ.get('FUTUREVIEW_OUTPUT','strategy1-layer2-15d-walkforward-audit.csv')


def metrics(name, out):
    p=out.pred_p_up.to_numpy(float); y=(out.actual_r3.to_numpy(float)>0).astype(float)
    rho=float(pd.Series(out.actual_r3).corr(pd.Series(out.pred_p_up),method='spearman'))
    brier=float(np.mean((p-y)**2)); bias=float(p.mean()-y.mean())
    lo,hi=out.pred_p_up.quantile([.2,.8]); bot=out[out.pred_p_up<=lo]; top=out[out.pred_p_up>=hi]
    print(f'S1 WF SUMMARY memory={name} n={len(out)} folds={out.fold_id.nunique()} pred_mean={p.mean():.6f} observed_up={y.mean():.6f} bias={bias:.6f} brier={brier:.6f} spearman={rho:.6f}')
    print(f'S1 WF BUCKET memory={name} bottom_n={len(bot)} bottom_up={(bot.actual_r3>0).mean():.6f} bottom_ret={bot.actual_r3.mean():.6f} top_n={len(top)} top_up={(top.actual_r3>0).mean():.6f} top_ret={top.actual_r3.mean():.6f}')


def main():
    if W!=30 or MODEL_HISTORY!=90 or HORIZON!=3: raise ValueError('locked to W30/L90/future3')
    torch.set_num_threads(2)
    df=download_ticker_daily(TICKER,period=DATA_PERIOD).reset_index(drop=True); validate_daily_ohlcv(df,minimum_rows=1800)
    paths=build_deterministic_path_table(add_strategy1_events(df).reset_index(drop=True))
    ce=classify_causal(build_cq(df,paths,membership='entry').rename(columns={'B':'B_periodic'}))
    cx=classify_causal(build_cq(df,paths,membership='exit').rename(columns={'B':'B_periodic'}))
    states=ce[['start_index','end_index','state']].merge(cx[['start_index','end_index','state']],on=['start_index','end_index'],suffixes=('_entry','_exit')).sort_values('end_index')
    data:PriceDistributionData=build_samples(df,states)
    rows=data.rows.copy().reset_index(drop=True); rows['cutoff_date']=pd.to_datetime(rows.cutoff_date)
    trading_dates=pd.to_datetime(df['date']).reset_index(drop=True)
    all_out=[]
    # Calendar trading-day blocks: retrain at every 15th trading-session boundary.
    first_cut=int(rows.cutoff_index.min()); last_cut=int(rows.cutoff_index.max())
    boundaries=list(range(first_cut,last_cut+1,ROLL_DAYS))
    for mem in MEMORIES:
        outs=[]; fid=0
        for start in boundaries:
            end=min(start+ROLL_DAYS-1,last_cut)
            va=(rows.cutoff_index>=start)&(rows.cutoff_index<=end)
            if not va.any(): continue
            # Causal purge: training labels must be fully realized before validation block starts.
            eligible=rows.cutoff_index <= (start-PURGE_DAYS-1)
            idx=np.flatnonzero(eligible.to_numpy())
            if len(idx)<mem: continue
            tr_idx=idx[-mem:]
            va_idx=np.flatnonzero(va.to_numpy())
            model=train(data.x[torch.from_numpy(tr_idx)],data.y[torch.from_numpy(tr_idx)],0.5,True)
            model.eval()
            with torch.no_grad():
                _,logit=model(data.x[torch.from_numpy(va_idx)]); p=torch.sigmoid(logit).numpy()
            f=rows.iloc[va_idx].copy().reset_index(drop=True); f['pred_p_up']=p; f['memory']=mem; f['fold_id']=fid; f['block_start_index']=start; f['block_end_index']=end; f['train_n']=len(tr_idx)
            outs.append(f); fid+=1
        if outs:
            out=pd.concat(outs,ignore_index=True).sort_values('cutoff_index').reset_index(drop=True); metrics(mem,out); all_out.append(out)
    if not all_out: raise RuntimeError('no eligible walk-forward folds')
    pd.concat(all_out,ignore_index=True).to_csv(OUTPUT,index=False)
    print(f'S1 WF START ticker={TICKER} roll_days={ROLL_DAYS} purge_days={PURGE_DAYS} memories={MEMORIES}')
    print('S1 WF COMPLETE')

if __name__=='__main__': main()
