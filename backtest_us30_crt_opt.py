import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
from datetime import datetime

np.random.seed(42)

SYMBOL = "YM=F"  # Dow futures proxy for US30
INTERVAL = "15m"
PERIOD = "60d"
INITIAL_EQUITY = 100000.0
RISK_PER_TRADE = 0.0025  # 0.25%
MAX_LEVERAGE = 3.0
COMMISSION_PCT = 0.0001  # 0.01%
SLIPPAGE_PCT = 0.00005


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

    htf = d.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
    htf['ema_fast'] = htf['Close'].ewm(span=p.ema_fast, adjust=False).mean()
    htf['ema_slow'] = htf['Close'].ewm(span=p.ema_slow, adjust=False).mean()
    htf['bull'] = (htf['Close'] > htf['ema_fast']) & (htf['ema_fast'] > htf['ema_slow'])
    htf['bear'] = (htf['Close'] < htf['ema_fast']) & (htf['ema_fast'] < htf['ema_slow'])

    d = d.join(htf[['bull','bear']], how='left')
    d[['bull','bear']] = d[['bull','bear']].ffill().fillna(False)

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
    in_pos = 0  # 1 long, -1 short
    entry = sl = tp = size_frac = 0.0
    trades = []
    eq_curve = []

    idx = d.index
    for i in range(2, len(d)-1):
        row = d.iloc[i]
        nxt = d.iloc[i+1]

        # exit logic intrabar approximation
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
                pnl = equity * net_ret
                equity += pnl
                trades.append(net_ret)
                in_pos = 0

        # entry on next bar open
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
    mdd = max_drawdown(eq_curve) if len(eq_curve) else 0
    n = len(trades)
    win = np.mean([1 if t > 0 else 0 for t in trades]) if trades else 0
    pf = (sum(t for t in trades if t > 0) / abs(sum(t for t in trades if t < 0))) if any(t < 0 for t in trades) else np.nan

    bars = len(d)
    days = bars * 15 / (60*24)
    months = max(days / 30.0, 0.5)
    monthly = (1 + total_ret) ** (1 / months) - 1

    return {
        'trades': n,
        'win_rate': win,
        'profit_factor': pf,
        'total_return': total_ret,
        'monthly_return': monthly,
        'max_dd': mdd,
    }


def sample_params(n=1000):
    out = []
    for _ in range(n):
        ema_fast = np.random.randint(20, 101)
        ema_slow = np.random.randint(max(ema_fast + 30, 120), 301)
        out.append(Params(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            atr_len=np.random.randint(10, 31),
            rr=np.round(np.random.uniform(1.2, 3.2), 2),
            atr_sl_mult=np.round(np.random.uniform(0.6, 2.0), 2),
            range_lookback=np.random.randint(8, 41),
            range_atr_factor=np.round(np.random.uniform(0.8, 2.2), 2),
            min_atr_pct=np.round(np.random.uniform(0.05, 0.35), 3),
        ))
    return out


def main():
    df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[['Open','High','Low','Close']].dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)

    split = int(len(df) * 0.7)
    is_df = df.iloc[:split].copy()
    oos_df = df.iloc[split:].copy()

    records = []
    for p in sample_params(1000):
        is_m = backtest(is_df, p)
        oos_m = backtest(oos_df, p)
        records.append({
            **p.__dict__,
            'is_trades': is_m['trades'],
            'is_monthly': is_m['monthly_return'],
            'is_mdd': is_m['max_dd'],
            'is_pf': is_m['profit_factor'],
            'oos_trades': oos_m['trades'],
            'oos_monthly': oos_m['monthly_return'],
            'oos_mdd': oos_m['max_dd'],
            'oos_pf': oos_m['profit_factor'],
            'oos_win_rate': oos_m['win_rate'],
        })

    r = pd.DataFrame(records)
    # Robust scoring prioritizing DD constraint
    r['score'] = (
        (r['oos_monthly'].clip(lower=-1) * 4.0) +
        (r['oos_pf'].fillna(0).clip(upper=3) * 0.8) +
        (r['oos_win_rate'] * 0.8) +
        (r['oos_trades'].clip(upper=120) / 120 * 0.4) +
        ((0.03 - r['oos_mdd'].abs()).clip(lower=-0.2, upper=0.03) * 8.0)
    )

    constrained = r[(r['oos_mdd'].abs() <= 0.03) & (r['oos_trades'] >= 12)]
    top = constrained.sort_values('score', ascending=False).head(20) if len(constrained) else r.sort_values('score', ascending=False).head(20)

    out_csv = 'results_us30_crt_1000.csv'
    out_top = 'results_us30_crt_top20.csv'
    r.to_csv(out_csv, index=False)
    top.to_csv(out_top, index=False)

    summary = {
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'rows_total': int(len(r)),
        'rows_constrained': int(len(constrained)),
        'best_oos_monthly': float(top.iloc[0]['oos_monthly']),
        'best_oos_mdd': float(top.iloc[0]['oos_mdd']),
        'best_oos_pf': float(top.iloc[0]['oos_pf']) if pd.notna(top.iloc[0]['oos_pf']) else None,
        'best_params': top.iloc[0][['ema_fast','ema_slow','atr_len','rr','atr_sl_mult','range_lookback','range_atr_factor','min_atr_pct']].to_dict()
    }

    with open('results_us30_crt_summary.txt', 'w') as f:
        for k, v in summary.items():
            f.write(f"{k}: {v}\n")

    print('Done')
    for k, v in summary.items():
        print(f"{k}: {v}")


if __name__ == '__main__':
    main()
