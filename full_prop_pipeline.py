import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
from datetime import datetime, timedelta

np.random.seed(7)
pd.set_option('future.no_silent_downcasting', True)

SYMBOL = "YM=F"
INTERVAL = "60m"
DAYS = 180
INITIAL_EQUITY = 100000.0
RISK_PER_TRADE = 0.0025
MAX_LEVERAGE = 3.0
COMMISSION_PCT = 0.0001
SLIPPAGE_PCT = 0.00005
TARGET_MONTHLY = 0.07
MAX_DD = 0.03
BAR_MINUTES = 60


@dataclass
class Params:
    ema_fast: int
    ema_slow: int
    atr_len: int
    rr: float
    atr_sl_mult: float
    range_lookback: int
    range_atr_factor: float
    min_atr_pct: float


def fetch_data(symbol=SYMBOL):
    df = yf.download(symbol, period='6mo', interval=INTERVAL, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    if df.empty:
        raise RuntimeError('No se pudo descargar data 6mo')
    df = df[['Open', 'High', 'Low', 'Close']].dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def atr(df, n):
    prev_close = df['Close'].shift(1)
    tr = pd.concat([
        (df['High'] - df['Low']).abs(),
        (df['High'] - prev_close).abs(),
        (df['Low'] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def max_drawdown(equity_curve):
    peak = equity_curve.cummax()
    dd = (equity_curve / peak) - 1.0
    return dd.min()


def backtest(df, p: Params):
    d = df.copy()
    d['atr'] = atr(d, p.atr_len)
    d['atr_pct'] = d['atr'] / d['Close'] * 100.0

    htf = d.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}).dropna()
    htf['ema_fast'] = htf['Close'].ewm(span=p.ema_fast, adjust=False).mean()
    htf['ema_slow'] = htf['Close'].ewm(span=p.ema_slow, adjust=False).mean()
    htf['bull'] = (htf['Close'] > htf['ema_fast']) & (htf['ema_fast'] > htf['ema_slow'])
    htf['bear'] = (htf['Close'] < htf['ema_fast']) & (htf['ema_fast'] < htf['ema_slow'])

    d = d.join(htf[['bull', 'bear']], how='left')
    d[['bull', 'bear']] = d[['bull', 'bear']].ffill().fillna(False)
    d[['bull', 'bear']] = d[['bull', 'bear']].infer_objects(copy=False).astype(bool)

    d['range_high'] = d['High'].rolling(p.range_lookback).max()
    d['range_low'] = d['Low'].rolling(p.range_lookback).min()
    d['range_size'] = d['range_high'] - d['range_low']
    d['valid_range'] = d['range_size'] > (d['atr'] * p.range_atr_factor)

    low1 = d['Low'].shift(1)
    high1 = d['High'].shift(1)
    range_low2 = d['range_low'].shift(2)
    range_high2 = d['range_high'].shift(2)

    long_signal = d['valid_range'] & (low1 < range_low2) & (d['Close'] > range_low2) & (d['Close'] > d['Open'])
    short_signal = d['valid_range'] & (high1 > range_high2) & (d['Close'] < range_high2) & (d['Close'] < d['Open'])

    allow_vol = d['atr_pct'] >= p.min_atr_pct
    long_entry = d['bull'] & long_signal & allow_vol
    short_entry = d['bear'] & short_signal & allow_vol

    long_struct_sl = np.minimum(d['Low'].shift(1), d['range_low'].shift(1))
    short_struct_sl = np.maximum(d['High'].shift(1), d['range_high'].shift(1))

    long_sl = np.minimum(long_struct_sl, d['Close'] - d['atr'] * p.atr_sl_mult)
    short_sl = np.maximum(short_struct_sl, d['Close'] + d['atr'] * p.atr_sl_mult)

    equity = INITIAL_EQUITY
    in_pos = 0
    entry = sl = tp = size_frac = 0.0
    trades = []
    eq_curve = []

    for i in range(2, len(d) - 1):
        row = d.iloc[i]
        nxt = d.iloc[i + 1]

        if in_pos != 0:
            exit_price = None
            if in_pos == 1:
                hit_sl = row['Low'] <= sl
                hit_tp = row['High'] >= tp
                if hit_sl and hit_tp:
                    exit_price = sl
                elif hit_sl:
                    exit_price = sl
                elif hit_tp:
                    exit_price = tp
                if exit_price is not None:
                    gross_ret = (exit_price - entry) / entry
            else:
                hit_sl = row['High'] >= sl
                hit_tp = row['Low'] <= tp
                if hit_sl and hit_tp:
                    exit_price = sl
                elif hit_sl:
                    exit_price = sl
                elif hit_tp:
                    exit_price = tp
                if exit_price is not None:
                    gross_ret = (entry - exit_price) / entry

            if exit_price is not None:
                net_ret = gross_ret * size_frac - (COMMISSION_PCT + SLIPPAGE_PCT) * size_frac * 2
                equity += equity * net_ret
                trades.append(net_ret)
                in_pos = 0

        if in_pos == 0 and np.isfinite(row['atr']) and equity > 0:
            if bool(long_entry.iloc[i]) and np.isfinite(long_sl.iloc[i]):
                e = float(nxt['Open'])
                s = float(long_sl.iloc[i])
                risk = (e - s) / e if e > s else np.nan
                if np.isfinite(risk) and risk > 0.0005:
                    size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                    entry = e * (1 + SLIPPAGE_PCT)
                    sl = s
                    tp = entry + (entry - sl) * p.rr
                    in_pos = 1
            elif bool(short_entry.iloc[i]) and np.isfinite(short_sl.iloc[i]):
                e = float(nxt['Open'])
                s = float(short_sl.iloc[i])
                risk = (s - e) / e if s > e else np.nan
                if np.isfinite(risk) and risk > 0.0005:
                    size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                    entry = e * (1 - SLIPPAGE_PCT)
                    sl = s
                    tp = entry - (sl - entry) * p.rr
                    in_pos = -1

        eq_curve.append(equity)

    eq_curve = pd.Series(eq_curve)
    total_ret = (equity / INITIAL_EQUITY) - 1
    mdd = max_drawdown(eq_curve) if len(eq_curve) else 0.0
    win = np.mean([1 if t > 0 else 0 for t in trades]) if trades else 0.0
    pf = (sum(t for t in trades if t > 0) / abs(sum(t for t in trades if t < 0))) if any(t < 0 for t in trades) else np.nan

    bars = len(d)
    days = bars * BAR_MINUTES / (60 * 24)
    months = max(days / 30.0, 0.5)
    monthly = (1 + total_ret) ** (1 / months) - 1

    return {
        'trades': len(trades),
        'win_rate': win,
        'profit_factor': pf,
        'monthly_return': monthly,
        'max_dd': mdd,
        'trade_returns': trades,
    }


def random_params(n):
    arr = []
    for _ in range(n):
        ef = np.random.randint(20, 101)
        es = np.random.randint(max(ef + 30, 120), 301)
        arr.append(Params(
            ema_fast=ef,
            ema_slow=es,
            atr_len=np.random.randint(10, 31),
            rr=np.random.uniform(1.2, 3.2),
            atr_sl_mult=np.random.uniform(0.6, 2.1),
            range_lookback=np.random.randint(8, 41),
            range_atr_factor=np.random.uniform(0.8, 2.2),
            min_atr_pct=np.random.uniform(0.05, 0.35),
        ))
    return arr


def score(m):
    return (
        m['monthly_return'] * 5
        + (0 if pd.isna(m['profit_factor']) else min(3.5, m['profit_factor'])) * 0.8
        + m['win_rate'] * 0.6
        + min(120, m['trades']) / 120 * 0.4
        + max(-0.25, min(0.03, 0.03 - abs(m['max_dd']))) * 10
    )


def walk_forward(df, p, train_days=60, test_days=20):
    start = df.index.min()
    end = df.index.max()
    cur = start
    vals = []
    while True:
        tr_end = cur + timedelta(days=train_days)
        te_end = tr_end + timedelta(days=test_days)
        if te_end > end:
            break
        test = df[(df.index >= tr_end) & (df.index < te_end)]
        if len(test) < 100:
            break
        vals.append(backtest(test, p))
        cur = cur + timedelta(days=test_days)
    if not vals:
        return None
    return {
        'wf_windows': len(vals),
        'wf_monthly_avg': float(np.mean([v['monthly_return'] for v in vals])),
        'wf_dd_worst': float(np.min([v['max_dd'] for v in vals])),
        'wf_pass_rate': float(np.mean([1 if (v['monthly_return'] > 0 and abs(v['max_dd']) <= MAX_DD) else 0 for v in vals]))
    }


def monte_carlo(trade_returns, n=1000):
    if len(trade_returns) < 10:
        return None
    arr = np.array(trade_returns)
    finals, mdds = [], []
    for _ in range(n):
        sampled = np.random.choice(arr, size=len(arr), replace=True)
        eq = [1.0]
        for r in sampled:
            eq.append(eq[-1] * (1 + r))
        eq = pd.Series(eq)
        finals.append(eq.iloc[-1] - 1)
        mdds.append(max_drawdown(eq))
    return {
        'mc_p05_return': float(np.percentile(finals, 5)),
        'mc_p50_return': float(np.percentile(finals, 50)),
        'mc_p95_dd': float(np.percentile(mdds, 95)),
        'mc_prob_dd_breach': float(np.mean([1 if abs(d) > MAX_DD else 0 for d in mdds]))
    }


def main():
    df = fetch_data()
    split = int(len(df) * 0.7)
    is_df, oos_df = df.iloc[:split], df.iloc[split:]

    recs = []
    for p in random_params(4000):
        is_m = backtest(is_df, p)
        oos_m = backtest(oos_df, p)
        if oos_m['trades'] < 1:
            continue
        recs.append({
            'ema_fast': p.ema_fast, 'ema_slow': p.ema_slow, 'atr_len': p.atr_len,
            'rr': p.rr, 'atr_sl_mult': p.atr_sl_mult, 'range_lookback': p.range_lookback,
            'range_atr_factor': p.range_atr_factor, 'min_atr_pct': p.min_atr_pct,
            'is_monthly': is_m['monthly_return'], 'is_mdd': is_m['max_dd'], 'is_pf': is_m['profit_factor'],
            'oos_monthly': oos_m['monthly_return'], 'oos_mdd': oos_m['max_dd'], 'oos_pf': oos_m['profit_factor'],
            'oos_trades': oos_m['trades'], 'oos_win': oos_m['win_rate'],
            'score': score(oos_m), 'trade_returns_oos': oos_m['trade_returns']
        })

    r = pd.DataFrame(recs)
    if r.empty:
        raise RuntimeError("No quedaron configuraciones válidas; revisar data/condiciones")
    constrained = r[(r['oos_mdd'].abs() <= MAX_DD) & (r['oos_trades'] >= 1)]
    if constrained.empty:
        constrained = r.sort_values('score', ascending=False).head(30)
    top = constrained.sort_values('oos_monthly', ascending=False).head(10).copy()

    wf_rows = []
    for _, row in top.iterrows():
        p = Params(
            int(row.ema_fast), int(row.ema_slow), int(row.atr_len), float(row.rr),
            float(row.atr_sl_mult), int(row.range_lookback), float(row.range_atr_factor), float(row.min_atr_pct)
        )
        wf = walk_forward(df, p)
        mc = monte_carlo(row.trade_returns_oos, n=1000)
        wf_rows.append({
            **{k: row[k] for k in ['ema_fast','ema_slow','atr_len','rr','atr_sl_mult','range_lookback','range_atr_factor','min_atr_pct','oos_monthly','oos_mdd','oos_pf','oos_trades']},
            **(wf or {}),
            **(mc or {}),
        })

    wfdf = pd.DataFrame(wf_rows)
    wfdf.to_csv('results_prop_wf_mc_top10.csv', index=False)

    r_out = r.drop(columns=['trade_returns_oos'])
    r_out.to_csv('results_prop_6mo_15m_all.csv', index=False)

    if wfdf.empty:
        best = pd.DataFrame()
    else:
        if 'wf_pass_rate' not in wfdf.columns:
            wfdf['wf_pass_rate'] = np.nan
        best = wfdf.sort_values(['oos_monthly','wf_pass_rate'], ascending=False).head(1)

    with open('results_prop_6mo_summary.txt', 'w') as f:
        f.write(f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"bars: {len(df)}\n")
        f.write(f"period_days: {DAYS}\n")
        f.write(f"tests_kept: {len(r)}\n")
        f.write(f"constrained: {len(constrained)}\n")
        if len(best):
            b = best.iloc[0]
            f.write(f"best_oos_monthly: {float(b['oos_monthly'])}\n")
            f.write(f"best_oos_dd: {float(b['oos_mdd'])}\n")
            f.write(f"best_wf_pass_rate: {float(b.get('wf_pass_rate', np.nan))}\n")
            f.write(f"best_mc_prob_dd_breach: {float(b.get('mc_prob_dd_breach', np.nan))}\n")
            f.write("best_params: " + str({
                'ema_fast': int(b['ema_fast']), 'ema_slow': int(b['ema_slow']), 'atr_len': int(b['atr_len']),
                'rr': float(b['rr']), 'atr_sl_mult': float(b['atr_sl_mult']), 'range_lookback': int(b['range_lookback']),
                'range_atr_factor': float(b['range_atr_factor']), 'min_atr_pct': float(b['min_atr_pct'])
            }) + "\n")

    print('Done')
    print('bars', len(df), 'tests_kept', len(r), 'constrained', len(constrained))
    if len(best):
        print(best[['oos_monthly','oos_mdd','wf_pass_rate','mc_prob_dd_breach']].to_string(index=False))


if __name__ == '__main__':
    main()
