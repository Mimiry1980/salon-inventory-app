import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

SYMBOL = "YM=F"
INTERVAL = "5m"
PERIOD = "60d"

INITIAL_EQUITY = 100000.0
RISK_PER_TRADE = 0.0025
MAX_LEVERAGE = 3.0
COMMISSION_PCT = 0.0001
SLIPPAGE_PCT = 0.00005

SESSION_START = (9, 30)
SESSION_END = (16, 0)

TOTAL_TESTS = 12000
CHUNK = 500
SEED = 77


def in_window(h, m, start, end):
    hm = h * 60 + m
    a = start[0] * 60 + start[1]
    b = end[0] * 60 + end[1]
    return a <= hm < b


def max_drawdown(eq):
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def add_15m_confirmation(df5):
    d15 = df5.resample('15min').agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
    d15['ema20'] = d15['Close'].ewm(span=20, adjust=False).mean()
    d15['bear_reversal'] = (d15['Close'] < d15['Open']) & (d15['Close'] < d15['ema20'])
    d15['bull_reversal'] = (d15['Close'] > d15['Open']) & (d15['Close'] > d15['ema20'])
    out = df5.join(d15[['bear_reversal','bull_reversal']], how='left')
    out[['bear_reversal','bull_reversal']] = out[['bear_reversal','bull_reversal']].ffill().fillna(False)
    return out


def sample_params(rng):
    return {
        'pivot_w': int(rng.choice([2, 3])),
        'rr': float(rng.choice([1.3, 1.4, 1.5, 1.6, 1.8])),
        'sl_points': float(rng.choice([100, 110, 120, 130, 140, 150, 160])),
        'max_trades_day': int(rng.choice([1, 2, 3])),
        'no_new_last_min': int(rng.choice([20, 30, 40, 50])),
        'wait_open': int(rng.choice([10, 15, 20, 25, 30])),
        'dt_tol': float(rng.choice([0.0006, 0.0008, 0.0010, 0.0012, 0.0015, 0.0020])),
        'db_tol': float(rng.choice([0.0006, 0.0008, 0.0010, 0.0012, 0.0015, 0.0020])),
        'min_bars': int(rng.choice([2, 3, 4, 5])),
        'max_bars': int(rng.choice([20, 24, 30, 40, 50, 60])),
        'cooldown': int(rng.choice([0, 2, 4, 6])),
    }


def backtest(d, p):
    pivot_w = p['pivot_w']
    rr = p['rr']
    sl_points = p['sl_points']
    max_trades_day = p['max_trades_day']
    no_new_last_min = p['no_new_last_min']
    wait_open = p['wait_open']
    dt_tol = p['dt_tol']
    db_tol = p['db_tol']
    min_bars = p['min_bars']
    max_bars = p['max_bars']
    cooldown_len = p['cooldown']

    ph = d['High'].rolling(2 * pivot_w + 1, center=True).max()
    pl = d['Low'].rolling(2 * pivot_w + 1, center=True).min()
    piv_h = (d['High'] == ph).values
    piv_l = (d['Low'] == pl).values

    equity = INITIAL_EQUITY
    in_pos = 0
    entry = sl = tp = size_frac = 0.0
    trades = []
    eq_curve = []

    day_prev = None
    trades_today = 0
    cooldown = 0

    last_ph_idx = None
    last_pl_idx = None

    n = len(d)
    idx = d.index
    highs = d['High'].values
    lows = d['Low'].values
    closes = d['Close'].values
    opens = d['Open'].values
    ny_h = d['ny_hour'].values
    ny_m = d['ny_min'].values
    bear15 = d['bear_reversal'].values
    bull15 = d['bull_reversal'].values

    for i in range(2 * pivot_w + 5, n - 1):
        h = int(ny_h[i]); m = int(ny_m[i])
        day = idx[i].date()

        if day_prev is None or day != day_prev:
            trades_today = 0
            day_prev = day
        if cooldown > 0:
            cooldown -= 1

        in_session = in_window(h, m, SESSION_START, SESSION_END)

        if in_pos != 0 and (h > SESSION_END[0] or (h == SESSION_END[0] and m >= SESSION_END[1])):
            gross = (closes[i] - entry) / entry if in_pos == 1 else (entry - closes[i]) / entry
            net = gross * size_frac - (COMMISSION_PCT + SLIPPAGE_PCT) * size_frac * 2
            equity += equity * net
            trades.append(net)
            if net < 0:
                cooldown = cooldown_len
            in_pos = 0

        if in_pos != 0:
            exit_price = None
            if in_pos == 1:
                if lows[i] <= sl:
                    exit_price = sl
                elif highs[i] >= tp:
                    exit_price = tp
                if exit_price is not None:
                    gross = (exit_price - entry) / entry
            else:
                if highs[i] >= sl:
                    exit_price = sl
                elif lows[i] <= tp:
                    exit_price = tp
                if exit_price is not None:
                    gross = (entry - exit_price) / entry
            if exit_price is not None:
                net = gross * size_frac - (COMMISSION_PCT + SLIPPAGE_PCT) * size_frac * 2
                equity += equity * net
                trades.append(net)
                if net < 0:
                    cooldown = cooldown_len
                in_pos = 0

        if piv_h[i]:
            last_ph_idx = i
        if piv_l[i]:
            last_pl_idx = i

        mins_to_close = SESSION_END[0] * 60 + SESSION_END[1] - (h * 60 + m)
        waited_open = (h * 60 + m) >= (SESSION_START[0] * 60 + SESSION_START[1] + wait_open)
        allow_new = in_session and mins_to_close > no_new_last_min and waited_open

        if in_pos == 0 and allow_new and trades_today < max_trades_day and cooldown == 0:
            short_signal = False
            long_signal = False

            if last_ph_idx is not None and (i - last_ph_idx) <= max_bars and bear15[i]:
                start = max(0, last_ph_idx - max_bars)
                prev_idxs = [j for j in range(start, last_ph_idx) if piv_h[j]]
                if prev_idxs:
                    prev_i = prev_idxs[-1]
                    if (last_ph_idx - prev_i) >= min_bars:
                        ph1 = highs[prev_i]; ph2 = highs[last_ph_idx]
                        avg_top = (ph1 + ph2) * 0.5
                        if avg_top > 0:
                            tops_close = abs(ph2 - ph1) / avg_top <= dt_tol
                            neckline = lows[prev_i:last_ph_idx+1].min()
                            if tops_close and closes[i] < neckline:
                                short_signal = True

            if last_pl_idx is not None and (i - last_pl_idx) <= max_bars and bull15[i]:
                start = max(0, last_pl_idx - max_bars)
                prev_idxs = [j for j in range(start, last_pl_idx) if piv_l[j]]
                if prev_idxs:
                    prev_i = prev_idxs[-1]
                    if (last_pl_idx - prev_i) >= min_bars:
                        pl1 = lows[prev_i]; pl2 = lows[last_pl_idx]
                        avg_bot = (pl1 + pl2) * 0.5
                        if avg_bot > 0:
                            bots_close = abs(pl2 - pl1) / avg_bot <= db_tol
                            neckline = highs[prev_i:last_pl_idx+1].max()
                            if bots_close and closes[i] > neckline:
                                long_signal = True

            if short_signal:
                e = opens[i+1] * (1 - SLIPPAGE_PCT)
                s = e + sl_points
                risk = (s - e) / e
                if risk > 0.0005:
                    size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                    entry = e; sl = s; tp = e - sl_points * rr
                    in_pos = -1; trades_today += 1
            elif long_signal:
                e = opens[i+1] * (1 + SLIPPAGE_PCT)
                s = e - sl_points
                risk = (e - s) / e
                if risk > 0.0005:
                    size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                    entry = e; sl = s; tp = e + sl_points * rr
                    in_pos = 1; trades_today += 1

        eq_curve.append(equity)

    eq_curve = pd.Series(eq_curve)
    total = equity / INITIAL_EQUITY - 1
    days = len(d) * 5 / (60 * 24)
    months = max(days / 30.0, 1.0)
    monthly = (1 + total) ** (1 / months) - 1
    wins = sum(1 for t in trades if t > 0)
    losses = sum(1 for t in trades if t < 0)
    pf = (sum(t for t in trades if t > 0) / abs(sum(t for t in trades if t < 0))) if losses > 0 else np.nan

    return {
        'trades': len(trades),
        'win_rate': wins / len(trades) if trades else 0.0,
        'profit_factor': float(pf) if pd.notna(pf) else np.nan,
        'total_return': float(total),
        'monthly_return': float(monthly),
        'max_dd': float(max_drawdown(eq_curve)),
    }


def main():
    rng = np.random.default_rng(SEED)
    df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[['Open','High','Low','Close','Volume']].dropna()

    idx = pd.to_datetime(df.index)
    if idx.tz is None:
        idx = idx.tz_localize('UTC')
    idx_ny = idx.tz_convert('America/New_York')
    df.index = idx_ny.tz_localize(None)
    df['ny_hour'] = idx_ny.hour
    df['ny_min'] = idx_ny.minute
    df = add_15m_confirmation(df)

    rows = []
    best = None

    for i in range(1, TOTAL_TESTS + 1):
        p = sample_params(rng)
        m = backtest(df, p)
        row = {**p, **m}
        rows.append(row)
        score = (
            (row['profit_factor'] if not np.isnan(row['profit_factor']) else 0) * 1.6
            + row['monthly_return'] * 10
            + max(-0.3, min(0.03, 0.03 - abs(row['max_dd']))) * 6
            + min(120, row['trades']) / 120 * 0.25
        )
        row['score'] = score

        if best is None or score > best['score']:
            best = row.copy()

        if i % CHUNK == 0:
            print(f"{datetime.now().isoformat(timespec='seconds')} tested={i} best_pf={best['profit_factor']:.3f} best_monthly={best['monthly_return']:.4f} best_dd={best['max_dd']:.4f}")

    r = pd.DataFrame(rows)
    r['score'] = (
        r['profit_factor'].fillna(0) * 1.6
        + r['monthly_return'] * 10
        + (0.03 - r['max_dd'].abs()).clip(lower=-0.3, upper=0.03) * 6
        + (r['trades'].clip(upper=120) / 120) * 0.25
    )

    top = r.sort_values('score', ascending=False).head(50)
    r.to_csv('results_us30_overnight_all.csv', index=False)
    top.to_csv('results_us30_overnight_top50.csv', index=False)

    b = top.iloc[0]
    with open('results_us30_overnight_summary.txt', 'w') as f:
        f.write(f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"tests: {TOTAL_TESTS}\n")
        f.write(f"best_profit_factor: {float(b['profit_factor'])}\n")
        f.write(f"best_monthly_return: {float(b['monthly_return'])}\n")
        f.write(f"best_max_dd: {float(b['max_dd'])}\n")
        f.write(f"best_trades: {int(b['trades'])}\n")
        f.write("best_params: " + str({
            'pivot_w': int(b['pivot_w']),
            'rr': float(b['rr']),
            'sl_points': float(b['sl_points']),
            'max_trades_day': int(b['max_trades_day']),
            'no_new_last_min': int(b['no_new_last_min']),
            'wait_open': int(b['wait_open']),
            'dt_tol': float(b['dt_tol']),
            'db_tol': float(b['db_tol']),
            'min_bars': int(b['min_bars']),
            'max_bars': int(b['max_bars']),
            'cooldown': int(b['cooldown'])
        }) + "\n")

    print("DONE")
    print(top.iloc[0][['profit_factor','monthly_return','max_dd','trades']].to_dict())


if __name__ == '__main__':
    main()
