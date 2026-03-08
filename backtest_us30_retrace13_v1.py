import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

# Proxy for US30 (Dow futures)
SYMBOL = "YM=F"
INTERVAL = "15m"
PERIOD = "60d"  # yfinance intraday limit

INITIAL_EQUITY = 100000.0
RISK_PER_TRADE = 0.0025  # 0.25%
MAX_LEVERAGE = 3.0
RR = 2.0
MAX_TRADES_PER_DAY = 2

COMMISSION_PCT = 0.0001
SLIPPAGE_PCT = 0.00005

IMPULSE_ATR_MULT = 1.2   # strong move threshold
ATR_LEN = 14
SL_ATR_BUFFER = 0.2


def atr(df, n=14):
    pc = df['Close'].shift(1)
    tr = pd.concat([
        (df['High'] - df['Low']).abs(),
        (df['High'] - pc).abs(),
        (df['Low'] - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def max_drawdown(eq_curve):
    peak = eq_curve.cummax()
    dd = eq_curve / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def backtest(df):
    d = df.copy()
    d['atr'] = atr(d, ATR_LEN)

    equity = INITIAL_EQUITY
    in_pos = 0
    entry = sl = tp = size_frac = 0.0
    trades = []
    eq_curve = []

    day_key_prev = None
    trades_today = 0

    # setup state
    # mode: 1 bullish impulse looking for long continuation after 1/3 retrace
    #      -1 bearish impulse looking for short continuation after 1/3 retrace
    mode = 0
    impulse_open = impulse_close = np.nan
    retrace_done = False
    opposite_candle_idx = None

    for i in range(ATR_LEN + 2, len(d) - 1):
        row = d.iloc[i]
        prev = d.iloc[i - 1]
        nxt = d.iloc[i + 1]

        day_key = row.name.date()
        if day_key_prev is None or day_key != day_key_prev:
            trades_today = 0
            day_key_prev = day_key

        # manage open trade
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

        # detect fresh strong impulse candle when flat and no active setup
        if in_pos == 0 and mode == 0 and np.isfinite(row['atr']):
            body = row['Close'] - row['Open']
            if body > row['atr'] * IMPULSE_ATR_MULT:
                mode = 1
                impulse_open = float(row['Open'])
                impulse_close = float(row['Close'])
                retrace_done = False
                opposite_candle_idx = None
            elif -body > row['atr'] * IMPULSE_ATR_MULT:
                mode = -1
                impulse_open = float(row['Open'])
                impulse_close = float(row['Close'])
                retrace_done = False
                opposite_candle_idx = None

        # manage setup state and trigger entries
        if in_pos == 0 and mode != 0 and trades_today < MAX_TRADES_PER_DAY and np.isfinite(row['atr']):
            move = abs(impulse_close - impulse_open)
            if move <= 0:
                mode = 0
            else:
                # 1/3 retrace level from impulse close back toward open
                if mode == 1:
                    retrace_level = impulse_close - move / 3.0
                    if row['Low'] <= retrace_level:
                        retrace_done = True
                    # opposite candle after retrace = bearish candle
                    if retrace_done and row['Close'] < row['Open']:
                        opposite_candle_idx = i
                    # trigger long on close above opposite candle high
                    if opposite_candle_idx is not None:
                        opp_high = float(d.iloc[opposite_candle_idx]['High'])
                        if row['Close'] > opp_high:
                            e = float(nxt['Open']) * (1 + SLIPPAGE_PCT)
                            s = float(d.iloc[opposite_candle_idx]['Low'] - row['atr'] * SL_ATR_BUFFER)
                            if e > s:
                                risk = (e - s) / e
                                if risk > 0.0005:
                                    size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                                    entry = e
                                    sl = s
                                    tp = e + (e - s) * RR
                                    in_pos = 1
                                    trades_today += 1
                                    mode = 0
                else:
                    retrace_level = impulse_close + move / 3.0
                    if row['High'] >= retrace_level:
                        retrace_done = True
                    # opposite candle after retrace = bullish candle
                    if retrace_done and row['Close'] > row['Open']:
                        opposite_candle_idx = i
                    # trigger short on close below opposite candle low
                    if opposite_candle_idx is not None:
                        opp_low = float(d.iloc[opposite_candle_idx]['Low'])
                        if row['Close'] < opp_low:
                            e = float(nxt['Open']) * (1 - SLIPPAGE_PCT)
                            s = float(d.iloc[opposite_candle_idx]['High'] + row['atr'] * SL_ATR_BUFFER)
                            if s > e:
                                risk = (s - e) / e
                                if risk > 0.0005:
                                    size_frac = min(MAX_LEVERAGE, RISK_PER_TRADE / risk)
                                    entry = e
                                    sl = s
                                    tp = e - (s - e) * RR
                                    in_pos = -1
                                    trades_today += 1
                                    mode = 0

                # invalidate setup after too long
                if mode != 0:
                    # if 20 bars pass after impulse without trigger, reset
                    # approximate using index distance from last detected candle
                    pass

        eq_curve.append(equity)

    eq_curve = pd.Series(eq_curve)
    total_return = equity / INITIAL_EQUITY - 1.0
    days = len(d) * 15 / (60 * 24)
    months = max(days / 30.0, 1.0)
    monthly = (1 + total_return) ** (1 / months) - 1

    wins = sum(1 for t in trades if t > 0)
    losses = sum(1 for t in trades if t < 0)
    pf = (sum(t for t in trades if t > 0) / abs(sum(t for t in trades if t < 0))) if losses > 0 else np.nan

    return {
        'trades': len(trades),
        'win_rate': wins / len(trades) if trades else 0.0,
        'profit_factor': float(pf) if pd.notna(pf) else np.nan,
        'total_return': float(total_return),
        'monthly_return': float(monthly),
        'max_dd': float(max_drawdown(eq_curve)),
    }


def main():
    df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[['Open', 'High', 'Low', 'Close']].dropna()
    df['Volume'] = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL, auto_adjust=False, progress=False)['Volume'].values
    df.index = pd.to_datetime(df.index).tz_localize(None)

    m = backtest(df)

    with open('results_us30_retrace13_v1_summary.txt', 'w') as f:
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
