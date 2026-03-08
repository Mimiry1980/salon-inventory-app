import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
from datetime import datetime

np.random.seed(42)

SYMBOL = 'NQ=F'   # Nasdaq futures proxy
INTERVAL = '60m'  # 6 months available in yfinance
PERIOD = '6mo'
INITIAL_EQUITY = 100000.0
RISK_PER_TRADE = 0.0025
MAX_LEVERAGE = 3.0
COMMISSION_PCT = 0.00012
SLIPPAGE_PCT = 0.00007

@dataclass
class Params:
    ema_fast: int
    ema_slow: int
    breakout_len: int
    atr_len: int
    atr_sl_mult: float
    rr: float
    vol_len: int
    vol_factor: float


def atr(df, n):
    pc = df['Close'].shift(1)
    tr = pd.concat([
        (df['High'] - df['Low']).abs(),
        (df['High'] - pc).abs(),
        (df['Low'] - pc).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def max_drawdown(eq):
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def backtest(df, p: Params):
    d = df.copy()
    d['ema_f'] = d['Close'].ewm(span=p.ema_fast, adjust=False).mean()
    d['ema_s'] = d['Close'].ewm(span=p.ema_slow, adjust=False).mean()
    d['atr'] = atr(d, p.atr_len)
    d['vol_ma'] = d['Volume'].rolling(p.vol_len).mean()

    d['bh'] = d['High'].rolling(p.breakout_len).max().shift(1)
    d['bl'] = d['Low'].rolling(p.breakout_len).min().shift(1)

    trend_up = d['ema_f'] > d['ema_s']
    trend_dn = d['ema_f'] < d['ema_s']
    vol_ok = d['Volume'] > (d['vol_ma'] * p.vol_factor)

    long_entry = trend_up & vol_ok & (d['Close'] > d['bh'])
    short_entry = trend_dn & vol_ok & (d['Close'] < d['bl'])

    equity = INITIAL_EQUITY
    in_pos = 0
    entry = sl = tp = size_frac = 0.0
    trades = []
    eq_curve = []

    for i in range(max(p.breakout_len, p.atr_len, p.ema_slow, p.vol_len) + 2, len(d)-1):
        row = d.iloc[i]
        nxt = d.iloc[i+1]

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
                    gross = (exit_price - entry) / entry
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
                    gross = (entry - exit_price) / entry

            if exit_price is not None:
                net = gross * size_frac - (COMMISSION_PCT + SLIPPAGE_PCT) * size_frac * 2
                equity += equity * net
                trades.append(net)
                in_pos = 0

        if in_pos == 0 and np.isfinite(row['atr']) and equity > 0:
            if bool(long_entry.iloc[i]):
                e = float(nxt['Open']) * (1 + SLIPPAGE_PCT)
                s = float(row['Close'] - row['atr'] * p.atr_sl_mult)
                if e > s:
                    risk = (e - s) / e
                    if risk > 0.0005:
                        size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                        entry = e
                        sl = s
                        tp = e + (e - s) * p.rr
                        in_pos = 1
            elif bool(short_entry.iloc[i]):
                e = float(nxt['Open']) * (1 - SLIPPAGE_PCT)
                s = float(row['Close'] + row['atr'] * p.atr_sl_mult)
                if s > e:
                    risk = (s - e) / e
                    if risk > 0.0005:
                        size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                        entry = e
                        sl = s
                        tp = e - (s - e) * p.rr
                        in_pos = -1

        eq_curve.append(equity)

    eq_curve = pd.Series(eq_curve)
    total = equity / INITIAL_EQUITY - 1.0
    days = len(d) * 60 / (60 * 24)
    months = max(days / 30.0, 1.0)
    monthly = (1 + total) ** (1 / months) - 1
    pf = (sum(t for t in trades if t > 0) / abs(sum(t for t in trades if t < 0))) if any(t < 0 for t in trades) else np.nan
    win = float(np.mean([1 if t > 0 else 0 for t in trades])) if trades else 0.0

    return {
        'trades': len(trades),
        'monthly': float(monthly),
        'total': float(total),
        'mdd': float(max_drawdown(eq_curve)),
        'pf': float(pf) if pd.notna(pf) else np.nan,
        'win': win,
    }


def sample(n=1000):
    out = []
    for _ in range(n):
        ef = np.random.randint(10, 51)
        es = np.random.randint(max(ef+20, 40), 201)
        out.append(Params(
            ema_fast=ef,
            ema_slow=es,
            breakout_len=np.random.randint(8, 49),
            atr_len=np.random.randint(8, 31),
            atr_sl_mult=float(np.round(np.random.uniform(0.8, 2.5), 2)),
            rr=float(np.round(np.random.uniform(1.2, 3.6), 2)),
            vol_len=np.random.randint(8, 41),
            vol_factor=float(np.round(np.random.uniform(0.8, 1.8), 2)),
        ))
    return out


def main():
    df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[['Open','High','Low','Close','Volume']].dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)

    split = int(len(df) * 0.7)
    is_df = df.iloc[:split]
    oos_df = df.iloc[split:]

    rows = []
    for p in sample(1000):
        is_m = backtest(is_df, p)
        oos_m = backtest(oos_df, p)
        rows.append({
            **p.__dict__,
            'is_monthly': is_m['monthly'], 'is_mdd': is_m['mdd'], 'is_pf': is_m['pf'], 'is_trades': is_m['trades'],
            'oos_monthly': oos_m['monthly'], 'oos_mdd': oos_m['mdd'], 'oos_pf': oos_m['pf'],
            'oos_trades': oos_m['trades'], 'oos_win': oos_m['win']
        })

    r = pd.DataFrame(rows)
    constrained = r[(r['oos_mdd'].abs() <= 0.03) & (r['oos_trades'] >= 8)]
    if constrained.empty:
        constrained = r.copy()

    constrained['score'] = (
        constrained['oos_monthly'] * 5
        + constrained['oos_pf'].fillna(0).clip(upper=4) * 0.8
        + constrained['oos_win'] * 0.6
        + (constrained['oos_trades'].clip(upper=120) / 120) * 0.3
        + (0.03 - constrained['oos_mdd'].abs()).clip(lower=-0.3, upper=0.03) * 8
    )

    top = constrained.sort_values('score', ascending=False).head(30)
    r.to_csv('results_clutix_6mo_1000_all.csv', index=False)
    top.to_csv('results_clutix_6mo_1000_top30.csv', index=False)

    b = top.iloc[0]
    with open('results_clutix_6mo_1000_summary.txt', 'w') as f:
        f.write(f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"bars: {len(df)}\n")
        f.write(f"tests: {len(r)}\n")
        f.write(f"constrained: {len(constrained)}\n")
        f.write(f"best_oos_monthly: {float(b['oos_monthly'])}\n")
        f.write(f"best_oos_mdd: {float(b['oos_mdd'])}\n")
        f.write(f"best_oos_pf: {float(b['oos_pf']) if pd.notna(b['oos_pf']) else None}\n")
        f.write(f"best_oos_trades: {int(b['oos_trades'])}\n")
        f.write("best_params: " + str({
            'ema_fast': int(b['ema_fast']),
            'ema_slow': int(b['ema_slow']),
            'breakout_len': int(b['breakout_len']),
            'atr_len': int(b['atr_len']),
            'atr_sl_mult': float(b['atr_sl_mult']),
            'rr': float(b['rr']),
            'vol_len': int(b['vol_len']),
            'vol_factor': float(b['vol_factor'])
        }) + "\n")

    print('Done')
    print('bars', len(df), 'tests', len(r), 'constrained', len(constrained))
    print('best monthly', float(b['oos_monthly']), 'mdd', float(b['oos_mdd']), 'pf', float(b['oos_pf']) if pd.notna(b['oos_pf']) else None)


if __name__ == '__main__':
    main()
