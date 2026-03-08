import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

SYMBOL = "YM=F"          # US30 proxy
INTERVAL = "15m"
PERIOD = "60d"

INITIAL_EQUITY = 100000.0
RISK_PER_TRADE = 0.0025
MAX_LEVERAGE = 3.0
MAX_TRADES_PER_DAY = 2
RR = 2.0

SL_POINTS = 150.0          # user rule: fixed 150 points
COOLDOWN_BARS_AFTER_LOSS = 4

COMMISSION_PCT = 0.0001
SLIPPAGE_PCT = 0.00005

SESSION_START = (9, 30)
SESSION_END = (16, 0)
RANGE_END = (11, 0)        # build NY AM range until 11:00
NO_NEW_TRADES_LAST_MIN = 30


def in_window(h, m, start, end):
    hm = h * 60 + m
    a = start[0] * 60 + start[1]
    b = end[0] * 60 + end[1]
    return a <= hm < b


def max_drawdown(eq):
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def backtest(df):
    d = df.copy()

    equity = INITIAL_EQUITY
    in_pos = 0
    entry = sl = tp = size_frac = 0.0
    trades = []
    eq_curve = []

    day_prev = None
    trades_today = 0
    cooldown = 0

    # NY morning range state per day
    day_high = np.nan
    day_low = np.nan
    range_locked = False

    for i in range(2, len(d) - 1):
        row = d.iloc[i]
        nxt = d.iloc[i + 1]

        h = int(row['ny_hour'])
        m = int(row['ny_min'])
        day = row.name.date()

        # new day reset
        if day_prev is None or day != day_prev:
            trades_today = 0
            cooldown = max(0, cooldown - 1)
            day_high = -np.inf
            day_low = np.inf
            range_locked = False
            day_prev = day

        if cooldown > 0:
            cooldown -= 1

        in_session = in_window(h, m, SESSION_START, SESSION_END)

        # build morning range 09:30-11:00
        if in_window(h, m, SESSION_START, RANGE_END):
            day_high = max(day_high, float(row['High']))
            day_low = min(day_low, float(row['Low']))

        if (h > RANGE_END[0] or (h == RANGE_END[0] and m >= RANGE_END[1])) and np.isfinite(day_high) and np.isfinite(day_low):
            range_locked = True

        # force close at NY close
        if in_pos != 0 and (h > SESSION_END[0] or (h == SESSION_END[0] and m >= SESSION_END[1])):
            gross = (row['Close'] - entry) / entry if in_pos == 1 else (entry - row['Close']) / entry
            net = gross * size_frac - (COMMISSION_PCT + SLIPPAGE_PCT) * size_frac * 2
            equity += equity * net
            trades.append(net)
            if net < 0:
                cooldown = COOLDOWN_BARS_AFTER_LOSS
            in_pos = 0

        # normal exits
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
                if net < 0:
                    cooldown = COOLDOWN_BARS_AFTER_LOSS
                in_pos = 0

        # entries
        mins_to_close = SESSION_END[0] * 60 + SESSION_END[1] - (h * 60 + m)
        allow_new = in_session and mins_to_close > NO_NEW_TRADES_LAST_MIN

        if in_pos == 0 and allow_new and range_locked and trades_today < MAX_TRADES_PER_DAY and cooldown == 0:
            # reversal short: sweep above range high then close back below it
            short_signal = (row['High'] > day_high) and (row['Close'] < day_high)
            # reversal long: sweep below range low then close back above it
            long_signal = (row['Low'] < day_low) and (row['Close'] > day_low)

            if short_signal:
                e = float(nxt['Open']) * (1 - SLIPPAGE_PCT)
                s = e + SL_POINTS
                risk = (s - e) / e
                if risk > 0.0005:
                    size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                    entry = e
                    sl = s
                    tp = e - SL_POINTS * RR
                    in_pos = -1
                    trades_today += 1
            elif long_signal:
                e = float(nxt['Open']) * (1 + SLIPPAGE_PCT)
                s = e - SL_POINTS
                risk = (e - s) / e
                if risk > 0.0005:
                    size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                    entry = e
                    sl = s
                    tp = e + SL_POINTS * RR
                    in_pos = 1
                    trades_today += 1

        eq_curve.append(equity)

    eq_curve = pd.Series(eq_curve)
    total = equity / INITIAL_EQUITY - 1.0
    days = len(d) * 15 / (60 * 24)
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
    df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()

    idx = pd.to_datetime(df.index)
    if idx.tz is None:
        idx = idx.tz_localize('UTC')
    idx_ny = idx.tz_convert('America/New_York')
    df.index = idx_ny.tz_localize(None)
    df['ny_hour'] = idx_ny.hour
    df['ny_min'] = idx_ny.minute

    m = backtest(df)

    with open('results_us30_reversal_fixed150_v1_summary.txt', 'w') as f:
        f.write(f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"symbol_proxy: {SYMBOL}\n")
        f.write(f"interval: {INTERVAL}\n")
        f.write(f"period: {PERIOD}\n")
        f.write(f"sl_points: {SL_POINTS}\n")
        f.write(f"rr: {RR}\n")
        f.write(f"max_trades_day: {MAX_TRADES_PER_DAY}\n")
        for k, v in m.items():
            f.write(f"{k}: {v}\n")

    print('Done')
    for k, v in m.items():
        print(f"{k}: {v}")


if __name__ == '__main__':
    main()
