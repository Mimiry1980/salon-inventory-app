import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
from datetime import datetime

np.random.seed(123)

SYMBOL = "YM=F"
INTERVAL = "15m"
PERIOD = "60d"
INITIAL_EQUITY = 100000.0
RISK_PER_TRADE = 0.0025
MAX_LEVERAGE = 3.0
COMMISSION_PCT = 0.0001
SLIPPAGE_PCT = 0.00005
TARGET_MONTHLY = 0.07
MAX_DD = 0.03


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


def clamp_params(p: Params) -> Params:
    ema_fast = int(np.clip(round(p.ema_fast), 20, 120))
    ema_slow = int(np.clip(round(p.ema_slow), max(ema_fast + 30, 120), 320))
    return Params(
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        atr_len=int(np.clip(round(p.atr_len), 8, 40)),
        rr=float(np.clip(p.rr, 1.1, 3.8)),
        atr_sl_mult=float(np.clip(p.atr_sl_mult, 0.5, 2.5)),
        range_lookback=int(np.clip(round(p.range_lookback), 6, 50)),
        range_atr_factor=float(np.clip(p.range_atr_factor, 0.6, 2.8)),
        min_atr_pct=float(np.clip(p.min_atr_pct, 0.03, 0.45)),
    )


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
    d[['bull', 'bear']] = d[['bull', 'bear']].ffill().fillna(False).astype(bool)

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
    days = bars * 15 / (60 * 24)
    months = max(days / 30.0, 0.5)
    monthly = (1 + total_ret) ** (1 / months) - 1

    return {
        'trades': len(trades),
        'win_rate': win,
        'profit_factor': pf,
        'monthly_return': monthly,
        'max_dd': mdd,
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


def mutate(base: Params, n, scale):
    arr = []
    for _ in range(n):
        p = Params(
            ema_fast=base.ema_fast + np.random.normal(0, 18 * scale),
            ema_slow=base.ema_slow + np.random.normal(0, 26 * scale),
            atr_len=base.atr_len + np.random.normal(0, 5 * scale),
            rr=base.rr + np.random.normal(0, 0.4 * scale),
            atr_sl_mult=base.atr_sl_mult + np.random.normal(0, 0.25 * scale),
            range_lookback=base.range_lookback + np.random.normal(0, 7 * scale),
            range_atr_factor=base.range_atr_factor + np.random.normal(0, 0.35 * scale),
            min_atr_pct=base.min_atr_pct + np.random.normal(0, 0.04 * scale),
        )
        arr.append(clamp_params(p))
    return arr


def score(oos_monthly, oos_mdd, oos_pf, oos_win, oos_trades):
    return (
        (max(-1.0, oos_monthly) * 5.0)
        + (min(3.5, 0 if pd.isna(oos_pf) else oos_pf) * 0.8)
        + (oos_win * 0.6)
        + (min(120, oos_trades) / 120 * 0.4)
        + (max(-0.25, min(0.03, 0.03 - abs(oos_mdd))) * 10)
    )


def main():
    df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[['Open', 'High', 'Low', 'Close']].dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)

    split = int(len(df) * 0.7)
    is_df = df.iloc[:split]
    oos_df = df.iloc[split:]

    rounds = []
    all_rows = []
    seeds = random_params(1000)

    best_global = None
    for rnd in range(1, 13):
        batch = seeds if rnd == 1 else []
        if rnd > 1:
            top_bases = sorted(rounds[-1]['rows'], key=lambda x: x['score'], reverse=True)[:20]
            for i, r in enumerate(top_bases):
                batch.extend(mutate(r['params'], 45, scale=max(0.35, 1.0 - rnd * 0.06)))
            batch.extend(random_params(max(0, 1000 - len(batch))))
            batch = batch[:1000]

        rows = []
        for p in batch:
            is_m = backtest(is_df, p)
            oos_m = backtest(oos_df, p)
            sc = score(oos_m['monthly_return'], oos_m['max_dd'], oos_m['profit_factor'], oos_m['win_rate'], oos_m['trades'])
            row = {
                'round': rnd,
                'params': p,
                'ema_fast': p.ema_fast,
                'ema_slow': p.ema_slow,
                'atr_len': p.atr_len,
                'rr': p.rr,
                'atr_sl_mult': p.atr_sl_mult,
                'range_lookback': p.range_lookback,
                'range_atr_factor': p.range_atr_factor,
                'min_atr_pct': p.min_atr_pct,
                'is_monthly': is_m['monthly_return'],
                'is_mdd': is_m['max_dd'],
                'is_pf': is_m['profit_factor'],
                'oos_monthly': oos_m['monthly_return'],
                'oos_mdd': oos_m['max_dd'],
                'oos_pf': oos_m['profit_factor'],
                'oos_win_rate': oos_m['win_rate'],
                'oos_trades': oos_m['trades'],
                'score': sc,
            }
            rows.append(row)
            all_rows.append({k: v for k, v in row.items() if k != 'params'})

        rows_sorted = sorted(rows, key=lambda x: x['score'], reverse=True)
        best = rows_sorted[0]
        constrained = [r for r in rows if abs(r['oos_mdd']) <= MAX_DD and r['oos_trades'] >= 12]
        constrained_best = sorted(constrained, key=lambda x: x['oos_monthly'], reverse=True)[0] if constrained else None

        rounds.append({
            'round': rnd,
            'rows': rows,
            'best': best,
            'constrained_best': constrained_best,
            'n_constrained': len(constrained),
        })

        if (best_global is None) or (best['score'] > best_global['score']):
            best_global = best

        if constrained_best and constrained_best['oos_monthly'] >= TARGET_MONTHLY:
            break

    out = pd.DataFrame(all_rows)
    out.to_csv('results_us30_crt_multiround_all.csv', index=False)

    constrained_all = out[(out['oos_mdd'].abs() <= MAX_DD) & (out['oos_trades'] >= 12)]
    top_constrained = constrained_all.sort_values('oos_monthly', ascending=False).head(30)
    top_constrained.to_csv('results_us30_crt_multiround_top30.csv', index=False)

    achieved = len(top_constrained) > 0 and float(top_constrained.iloc[0]['oos_monthly']) >= TARGET_MONTHLY

    with open('results_us30_crt_multiround_summary.txt', 'w') as f:
        f.write(f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"rounds_run: {len(rounds)}\n")
        f.write(f"tests_total: {len(out)}\n")
        f.write(f"target_monthly: {TARGET_MONTHLY}\n")
        f.write(f"target_max_dd: {MAX_DD}\n")
        f.write(f"achieved_target: {achieved}\n")
        if len(top_constrained):
            b = top_constrained.iloc[0]
            f.write(f"best_oos_monthly: {float(b['oos_monthly'])}\n")
            f.write(f"best_oos_mdd: {float(b['oos_mdd'])}\n")
            f.write(f"best_oos_pf: {float(b['oos_pf']) if pd.notna(b['oos_pf']) else None}\n")
            f.write(f"best_round: {int(b['round'])}\n")
            f.write("best_params: " + str({
                'ema_fast': int(b['ema_fast']),
                'ema_slow': int(b['ema_slow']),
                'atr_len': int(b['atr_len']),
                'rr': float(b['rr']),
                'atr_sl_mult': float(b['atr_sl_mult']),
                'range_lookback': int(b['range_lookback']),
                'range_atr_factor': float(b['range_atr_factor']),
                'min_atr_pct': float(b['min_atr_pct']),
            }) + "\n")

    print('Done')
    print('rounds_run:', len(rounds))
    print('tests_total:', len(out))
    if len(top_constrained):
        b = top_constrained.iloc[0]
        print('best_oos_monthly:', float(b['oos_monthly']))
        print('best_oos_mdd:', float(b['oos_mdd']))
        print('best_oos_pf:', float(b['oos_pf']) if pd.notna(b['oos_pf']) else None)
        print('best_round:', int(b['round']))
        print('achieved_target:', achieved)


if __name__ == '__main__':
    main()
