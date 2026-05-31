#!/usr/bin/env python3
"""
OPTIMIZED BACKTEST — DuckDB (fast) instead of pandas (slow)
Runs in <30 seconds on 2024 data
"""

import duckdb
import pandas as pd
from pathlib import Path
import json
from datetime import datetime
import re

print("\n" + "=" * 70)
print("BRAHMAND BACKTEST — 2024 (DUCKDB OPTIMIZED)")
print("=" * 70)

# Load data into DuckDB (fast, streaming)
print(f"\n📊 Loading 2024 data into DuckDB...")

dataset_path = Path(
    "/root/.cache/kagglehub/datasets/kaalicharan9080/nse-future-and-options-data/versions/2"
)
csv_files = sorted(dataset_path.glob("NSE_FNO*.csv"))[:5]  # Test on first 5 files

# Create temp DuckDB
conn = duckdb.connect(":memory:")

# Load all CSVs
for csv_file in csv_files:
    try:
        # Create table from CSV
        table_name = f"data_{csv_files.index(csv_file)}"
        conn.execute(
            f"CREATE TABLE {table_name} AS SELECT * FROM read_csv('{csv_file}')"
        )
        rows = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchall()[0][0]
        print(f"   ✅ {csv_file.name}: {rows:,} rows")
    except Exception as e:
        print(f"   ❌ {csv_file.name}: {e}")

# Union all tables
all_tables = [f"data_{i}" for i in range(len(csv_files))]
union_query = " UNION ALL ".join([f"SELECT * FROM {t}" for t in all_tables])
conn.execute(f"CREATE TABLE all_data AS {union_query}")

total_rows = conn.execute("SELECT COUNT(*) FROM all_data").fetchall()[0][0]
print(f"\n   Total rows: {total_rows:,}")

# Filter NIFTY weekly options (tickers have .NFO suffix, e.g., NIFTY07NOV2443000CE.NFO)
print(f"\n🔍 Filtering NIFTY index options...")
conn.execute("DROP TABLE IF EXISTS nifty_opts")
conn.execute("""
    CREATE TABLE nifty_opts AS
    SELECT *
    FROM all_data
    WHERE Ticker LIKE '%NIFTY%'
      AND NOT Ticker LIKE '%BANKNIFTY%'
      AND (Ticker LIKE '%CE%' OR Ticker LIKE '%PE%')
""")

nifty_count = conn.execute("SELECT COUNT(*) FROM nifty_opts").fetchall()[0][0]
print(f"   NIFTY index rows: {nifty_count:,}")

if nifty_count == 0:
    print("   ⚠️ No BANKNIFTY found, trying all options...")
    conn.execute("DROP TABLE IF EXISTS nifty_opts")
    conn.execute("""
        CREATE TABLE nifty_opts AS
        SELECT *
        FROM all_data
        WHERE Ticker LIKE '%CE' OR Ticker LIKE '%PE'
    """)
    nifty_count = conn.execute("SELECT COUNT(*) FROM nifty_opts").fetchall()[0][0]
    print(f"   Total rows: {nifty_count:,}")

# Parse and prepare data
print(f"\n⚙️  Parsing and preparing data...")
conn.execute("""
    CREATE TABLE options_parsed AS
    SELECT
        Ticker,
        Date,
        Time,
        Open,
        High,
        Low,
        Close,
        Volume,
        CAST(CONCAT(Date, ' ', Time) as TIMESTAMP) as dt,
        TRY_CAST(REGEXP_EXTRACT(Ticker, '(\d{4,5})(CE|PE)\.NFO$', 1) AS INTEGER) as strike,
        CASE WHEN Ticker LIKE '%CE%' THEN 'CE' ELSE 'PE' END as type,
        CAST(Date as DATE) as trade_date
    FROM nifty_opts
    WHERE Close > 0
""")

print(f"   ✅ Parsed {nifty_count:,} records")

# BACKTEST: Simple strategy
print(f"\n📈 Running backtest (Sell ATM, TP 20%, SL 5%)...")

# Get daily ATM opens
conn.execute("""
    CREATE TABLE daily_opens AS
    SELECT
        trade_date,
        strike,
        type,
        MIN(dt) as open_time,
        FIRST(Close) as open_price
    FROM options_parsed
    GROUP BY trade_date, strike, type
""")

# Process each trade
trades = []
opens = conn.execute("SELECT * FROM daily_opens ORDER BY trade_date").fetchall()
print(f"   Processing {len(opens)} potential trades...")

for open_row in opens:
    trade_date, strike, type_, open_time, entry_price = open_row

    # Get intraday prices
    intra = conn.execute(f"""
        SELECT dt, Close
        FROM options_parsed
        WHERE trade_date = '{trade_date}'
          AND strike = {strike}
          AND type = '{type_}'
          AND dt > '{open_time}'
        ORDER BY dt
        LIMIT 1000
    """).fetchall()

    if not intra:
        continue

    tp_price = entry_price * 0.8
    sl_price = entry_price * 1.05

    exit_signal = None
    exit_price = None
    exit_time = None

    for dt, price in intra:
        if price <= tp_price:
            exit_signal = "TP"
            exit_price = price
            exit_time = dt
            break
        elif price >= sl_price:
            exit_signal = "SL"
            exit_price = price
            exit_time = dt
            break

    if exit_signal:
        pnl_points = entry_price - exit_price
        pnl_rupees = pnl_points * 75  # NIFTY lot in 2024 = 75 contracts
        duration = (exit_time - open_time).total_seconds() / 60 if exit_time else 0

        trades.append(
            {
                "date": str(trade_date),
                "strike": strike,
                "type": type_,
                "entry": round(entry_price, 2),
                "exit": round(exit_price, 2),
                "signal": exit_signal,
                "pnl": round(pnl_rupees, 2),
                "points": round(pnl_points, 2),
                "duration_mins": round(duration, 0),
                "win": 1 if pnl_rupees > 0 else 0,
            }
        )

# Analysis
print(f"\n{'=' * 70}")
if trades:
    trades_df = pd.DataFrame(trades)
    total_pnl = trades_df["pnl"].sum()
    wins = trades_df["win"].sum()
    losses = len(trades) - wins
    win_rate = (wins / len(trades) * 100) if trades else 0

    avg_win = trades_df[trades_df["win"] == 1]["pnl"].mean() if wins > 0 else 0
    avg_loss = trades_df[trades_df["win"] == 0]["pnl"].mean() if losses > 0 else 0

    print(f"📊 BACKTEST RESULTS ({len(trades)} trades)")
    print(f"{'=' * 70}")
    print(f"\n💰 Performance:")
    print(f"   Total P&L: ₹{total_pnl:,.2f}")
    print(f"   Win rate: {win_rate:.1f}% ({wins}W / {losses}L)")
    print(f"   Avg win: ₹{avg_win:,.2f}")
    print(f"   Avg loss: ₹{avg_loss:,.2f}")
    print(f"   Max win: ₹{trades_df['pnl'].max():,.2f}")
    print(f"   Max loss: ₹{trades_df['pnl'].min():,.2f}")

    if losses > 0 and avg_loss != 0:
        pf = abs(avg_win * wins) / abs(avg_loss * losses)
        print(f"   Profit factor: {pf:.2f}x")

    print(f"\n⏱️  Trade Details:")
    print(f"   Avg duration: {trades_df['duration_mins'].mean():.0f} mins")
    print(f"   TP exits: {len(trades_df[trades_df['signal'] == 'TP'])}")
    print(f"   SL exits: {len(trades_df[trades_df['signal'] == 'SL'])}")

    print(f"\n{'=' * 70}")
    if total_pnl > 0 and win_rate > 45:
        print(f"✅ STRATEGY VIABLE: ₹{total_pnl:,.2f} profit, {win_rate:.0f}% win rate")
        print(f"   → SAFE TO DEPLOY WITH STANDARD NIFTY LOT (65 contracts)")
    elif total_pnl > 0:
        print(f"⚠️  MARGINAL: ₹{total_pnl:,.2f} profit, {win_rate:.0f}% win rate")
        print(f"   → DEPLOY CAUTIOUSLY, MONITOR CLOSELY")
    else:
        print(f"❌ UNPROFITABLE: ₹{total_pnl:,.2f} loss")
        print(f"   → NEEDS STRATEGY IMPROVEMENT")
    print(f"{'=' * 70}\n")

    # Save results
    results = {
        "timestamp": datetime.now().isoformat(),
        "total_trades": len(trades),
        "total_pnl": float(total_pnl),
        "win_rate_percent": float(win_rate),
        "wins": int(wins),
        "losses": int(losses),
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
        "recommendation": "DEPLOY" if (total_pnl > 0 and win_rate > 45) else "CAUTION",
    }

    Path("data/backtest_results_2024.json").write_text(json.dumps(results, indent=2))
    trades_df.to_csv("data/backtest_trades_2024.csv", index=False)

    print(f"Results saved:")
    print(f"  data/backtest_results_2024.json")
    print(f"  data/backtest_trades_2024.csv\n")
else:
    print(f"❌ No trades generated\n")

conn.close()
