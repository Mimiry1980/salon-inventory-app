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
MAX_TRADES_PER_DAY = 2
RR = 2.0

SL_POINTS = 150.0
COOLDOWN_BARS_AFTER_LOSS = 4

COMMISSION_PCT = 0.0001
SLIPPAGE_PCT = 0.00005

SESSION_START = (9, 30)
SESSION_END = (16, 0)
NO_NEW_TRADES_LAST_MIN = 30

PIVOT_W = 2
DT_TOL_PCT = 0.0008
DB_TOL_PCT = 0.0008
MIN_BARS_BETWEEN_PEAKS = 3
MAX_BARS_BETWEEN_PEAKS = 24


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
    # Build 15m bars and derive simple reversal context
    d15 = df5.resample('15min').agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
    d15['ema20'] = d15['Close'].ewm(span=20, adjust=False).mean()

    # reversal clues on 15m
    d15['bear_reversal'] = (d15['Close'] < d15['Open']) & (d15['Close'] < d15['ema20'])
    d15['bull_reversal'] = (d15['Close'] > d15['Open']) & (d15['Close'] > d15['ema20'])

    out = df5.join(d15[['bear_reversal','bull_reversal']], how='left')
    out[['bear_reversal','bull_reversal']] = out[['bear_reversal','bull_reversal']].ffill().fillna(False)
    return out


def backtest(df):
    d = df.copy()

    ph = d['High'].rolling(2 * PIVOT_W + 1, center=True).max()
    pl = d['Low'].rolling(2 * PIVOT_W + 1, center=True).min()
    d['pivot_high'] = (d['High'] == ph)
    d['pivot_low'] = (d['Low'] == pl)

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

    for i in range(2 * PIVOT_W + 5, len(d) - 1):
        row = d.iloc[i]
        nxt = d.iloc[i + 1]

        h = int(row['ny_hour'])
        m = int(row['ny_min'])
        day = row.name.date()

        if day_prev is None or day != day_prev:
            trades_today = 0
            cooldown = max(0, cooldown - 1)
            day_prev = day

        if cooldown > 0:
            cooldown -= 1

        in_session = in_window(h, m, SESSION_START, SESSION_END)

        if in_pos != 0 and (h > SESSION_END[0] or (h == SESSION_END[0] and m >= SESSION_END[1])):
            gross = (row['Close'] - entry) / entry if in_pos == 1 else (entry - row['Close']) / entry
            net = gross * size_frac - (COMMISSION_PCT + SLIPPAGE_PCT) * size_frac * 2
            equity += equity * net
            trades.append(net)
            if net < 0:
                cooldown = COOLDOWN_BARS_AFTER_LOSS
            in_pos = 0

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

        if bool(d.iloc[i]['pivot_high']):
            last_ph_idx = i
        if bool(d.iloc[i]['pivot_low']):
            last_pl_idx = i

        mins_to_close = SESSION_END[0] * 60 + SESSION_END[1] - (h * 60 + m)
        allow_new = in_session and mins_to_close > NO_NEW_TRADES_LAST_MIN

        if in_pos == 0 and allow_new and trades_today < MAX_TRADES_PER_DAY and cooldown == 0:
            short_signal = False
            long_signal = False

            # 5m double top + 15m bearish confirmation
            if last_ph_idx is not None and (i - last_ph_idx) <= MAX_BARS_BETWEEN_PEAKS and bool(row['bear_reversal']):
                prev_candidates = d.iloc[max(0, last_ph_idx - MAX_BARS_BETWEEN_PEAKS):last_ph_idx]
                prev_piv = prev_candidates[prev_candidates['pivot_high']]
                if len(prev_piv) > 0:
                    prev_idx = prev_piv.index[-1]
                    prev_i = d.index.get_loc(prev_idx)
                    if (last_ph_idx - prev_i) >= MIN_BARS_BETWEEN_PEAKS:
                        ph1 = float(d.iloc[prev_i]['High'])
                        ph2 = float(d.iloc[last_ph_idx]['High'])
                        avg_top = (ph1 + ph2) / 2.0
                        tops_close = abs(ph2 - ph1) / avg_top <= DT_TOL_PCT
                        neckline = float(d.iloc[prev_i:last_ph_idx + 1]['Low'].min())
                        if tops_close and row['Close'] < neckline:
                            short_signal = True

            # 5m double bottom + 15m bullish confirmation
            if last_pl_idx is not None and (i - last_pl_idx) <= MAX_BARS_BETWEEN_PEAKS and bool(row['bull_reversal']):
                prev_candidates = d.iloc[max(0, last_pl_idx - MAX_BARS_BETWEEN_PEAKS):last_pl_idx]
                prev_piv = prev_candidates[prev_candidates['pivot_low']]
                if len(prev_piv) > 0:
                    prev_idx = prev_piv.index[-1]
                    prev_i = d.index.get_loc(prev_idx)
                    if (last_pl_idx - prev_i) >= MIN_BARS_BETWEEN_PEAKS:
                        pl1 = float(d.iloc[prev_i]['Low'])
                        pl2 = float(d.iloc[last_pl_idx]['Low'])
                        avg_bot = (pl1 + pl2) / 2.0
                        bots_close = abs(pl2 - pl1) / avg_bot <= DB_TOL_PCT
                        neckline = float(d.iloc[prev_i:last_pl_idx + 1]['High'].max())
                        if bots_close and row['Close'] > neckline:
                            long_signal = True

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

    df = add_15m_confirmation(df)

    m = backtest(df)

    with open('results_us30_hybrid_5m_15m_confirm_v1_summary.txt', 'w') as f:
        f.write(f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"symbol_proxy: {SYMBOL}\n")
        f.write(f"interval: {INTERVAL}\n")
        f.write(f"period: {PERIOD}\n")
        for k, v in m.items():
            f.write(f"{k}: {v}\n")

    print('Done')
    for k, v in m.items():
        print(f"{k}: {v}")


if __name__ == '__main__':
    main()
