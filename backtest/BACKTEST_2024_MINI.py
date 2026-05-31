#!/usr/bin/env python3
"""
BACKTEST 2024 DATA — Full strategy performance on Kaggle F&O data
Run this to see: Total P&L, Win Rate, Avg Win/Loss, Trade Count
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json
from datetime import datetime

print("\n" + "="*70)
print("BRAHMAND BACKTEST — 2024 KAGGLE DATA")
print("="*70)

# Load all 2024 data files
dataset_path = Path("/root/.cache/kagglehub/datasets/kaalicharan9080/nse-future-and-options-data/versions/2")
csv_files = sorted(dataset_path.glob("NSE_FNO*.csv"))

print(f"\n📊 Loading {len(csv_files)} data files...")

all_data = []
for csv_file in csv_files:
    try:
        df = pd.read_csv(csv_file)
        all_data.append(df)
        print(f"   ✅ {csv_file.name} ({len(df):,} rows)")
    except Exception as e:
        print(f"   ❌ {csv_file.name}: {e}")

data = pd.concat(all_data, ignore_index=True)
print(f"\n   Total rows: {len(data):,}")

# Filter for NIFTY options (main index, not BANKNIFTY)
print(f"\n🔍 Filtering for NIFTY options...")
nifty_data = data[
    (data['Ticker'].str.contains('NIFTY', case=False, na=False)) &
    (~data['Ticker'].str.contains('BANKNIFTY', case=False, na=False)) &
    (data['Ticker'].str.contains('PE|CE', regex=True, na=False))
].copy()

print(f"   NIFTY rows: {len(nifty_data):,}")
print(f"   Date range: {nifty_data['Date'].min()} to {nifty_data['Date'].max()}")

if len(nifty_data) == 0:
    print("   ⚠️  No NIFTY options found, using BANKNIFTY instead")
    nifty_data = data[
        (data['Ticker'].str.contains('BANKNIFTY', case=False, na=False)) &
        (data['Ticker'].str.contains('PE|CE', regex=True, na=False))
    ].copy()

# Parse ticker
print(f"\n⚙️  Parsing tickers...")
import re

def parse_ticker(ticker):
    # BANKNIFTY06NOV2443000CE or NIFTY26NOV24C23800
    match = re.search(r'(BANKNIFTY|NIFTY)(\d{2}[A-Z]{3}\d{2})(\d+)(CE|PE)', ticker)
    if match:
        return pd.Series({
            'expiry': match.group(2),
            'strike': int(match.group(3)),
            'type': match.group(4)
        })
    return pd.Series({'expiry': None, 'strike': None, 'type': None})

parsed = nifty_data['Ticker'].apply(parse_ticker)
nifty_data = pd.concat([nifty_data, parsed], axis=1)
nifty_data = nifty_data[nifty_data['strike'].notna()].copy()
nifty_data['datetime'] = pd.to_datetime(nifty_data['Date'] + ' ' + nifty_data['Time'], format='%d/%m/%Y %H:%M:%S')

print(f"   ✅ Parsed {len(nifty_data):,} records")
print(f"   Unique strikes: {nifty_data['strike'].nunique()}")
print(f"   Unique expirations: {nifty_data['expiry'].nunique()}")

# STRATEGY: Simple entry signals based on price action
# For testing: every ATM strike, sell at open, take profit at 20% or loss at 5%
print(f"\n📈 Running backtest with MINI strategy...")
print(f"   Entry: Sell ATM calls/puts at market open")
print(f"   TP: 20% profit (price down)")
print(f"   SL: 5% loss (price up)")
print(f"   Qty: 75 (1 MINI lot)")

trades = []
daily_atm = nifty_data.groupby(nifty_data['datetime'].dt.date).apply(
    lambda x: x[x['datetime'] == x['datetime'].min()]
).reset_index(drop=True)

print(f"\n🔄 Simulating trades on {len(daily_atm):,} daily opens...")

for idx, row in daily_atm.iterrows():
    entry_price = row['Close']
    entry_type = row['type']
    strike = row['strike']
    entry_date = row['datetime'].date()

    # Get all prices for this strike/type/date
    strike_data = nifty_data[
        (nifty_data['strike'] == strike) &
        (nifty_data['type'] == entry_type) &
        (nifty_data['datetime'].dt.date == entry_date)
    ].sort_values('datetime')

    if len(strike_data) < 2:
        continue

    tp_price = entry_price * 0.8  # 20% profit for short
    sl_price = entry_price * 1.05  # 5% loss

    exit_signal = None
    exit_price = None
    exit_idx = None

    for eidx, erow in strike_data.iloc[1:].iterrows():
        if erow['Close'] <= tp_price:
            exit_signal = 'TP'
            exit_price = erow['Close']
            exit_idx = eidx
            break
        elif erow['Close'] >= sl_price:
            exit_signal = 'SL'
            exit_price = erow['Close']
            exit_idx = eidx
            break

    if exit_signal:
        pnl_points = entry_price - exit_price
        pnl_rupees = pnl_points * 75  # MINI = 75 qty
        duration = (strike_data.loc[exit_idx, 'datetime'] - row['datetime']).total_seconds() / 60

        trades.append({
            'date': entry_date,
            'strike': strike,
            'type': entry_type,
            'entry': entry_price,
            'exit': exit_price,
            'signal': exit_signal,
            'pnl': pnl_rupees,
            'points': pnl_points,
            'duration_mins': duration,
            'win': 1 if pnl_rupees > 0 else 0
        })

# Analysis
if trades:
    trades_df = pd.DataFrame(trades)
    total_pnl = trades_df['pnl'].sum()
    win_count = trades_df['win'].sum()
    loss_count = len(trades_df) - win_count
    win_rate = (win_count / len(trades_df) * 100) if len(trades_df) > 0 else 0

    avg_win = trades_df[trades_df['win'] == 1]['pnl'].mean() if win_count > 0 else 0
    avg_loss = trades_df[trades_df['win'] == 0]['pnl'].mean() if loss_count > 0 else 0
    max_win = trades_df['pnl'].max()
    max_loss = trades_df['pnl'].min()

    print(f"\n{'='*70}")
    print(f"📊 BACKTEST RESULTS ({len(trades)} trades)")
    print(f"{'='*70}")
    print(f"\nPerformance:")
    print(f"  Total P&L: ₹{total_pnl:,.2f}")
    print(f"  Win rate: {win_rate:.1f}% ({win_count}W / {loss_count}L)")
    print(f"  Avg win: ₹{avg_win:,.2f}")
    print(f"  Avg loss: ₹{avg_loss:,.2f}")
    print(f"  Max win: ₹{max_win:,.2f}")
    print(f"  Max loss: ₹{max_loss:,.2f}")
    print(f"  Profit factor: {abs(avg_win * win_count) / abs(avg_loss * loss_count):.2f}x" if loss_count > 0 else "Inf")

    print(f"\nTrade Distribution:")
    print(f"  Avg duration: {trades_df['duration_mins'].mean():.0f} minutes")
    print(f"  TP exits: {len(trades_df[trades_df['signal']=='TP'])}")
    print(f"  SL exits: {len(trades_df[trades_df['signal']=='SL'])}")

    print(f"\n{'='*70}")
    if total_pnl > 0:
        print(f"✅ STRATEGY PROFITABLE: ₹{total_pnl:,.2f} on {len(trades)} trades")
    else:
        print(f"❌ STRATEGY LOSS: ₹{total_pnl:,.2f} on {len(trades)} trades")
    print(f"{'='*70}\n")

    # Save results
    results = {
        'timestamp': datetime.now().isoformat(),
        'total_trades': len(trades),
        'total_pnl': float(total_pnl),
        'win_rate_percent': float(win_rate),
        'wins': int(win_count),
        'losses': int(loss_count),
        'avg_win': float(avg_win),
        'avg_loss': float(avg_loss),
        'max_win': float(max_win),
        'max_loss': float(max_loss),
        'recommendation': 'DEPLOY_WITH_MINI' if total_pnl > 0 and win_rate > 50 else 'NEEDS_IMPROVEMENT'
    }

    Path('data/backtest_results_2024.json').write_text(json.dumps(results, indent=2))
    trades_df.to_csv('data/backtest_trades_2024.csv', index=False)

    print(f"Results saved:")
    print(f"  data/backtest_results_2024.json")
    print(f"  data/backtest_trades_2024.csv\n")

else:
    print(f"\n❌ No trades generated from backtest\n")
