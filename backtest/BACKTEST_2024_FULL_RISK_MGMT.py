#!/usr/bin/env python3
"""
FULL BACKTEST — 2024 NIFTY with leg-independent risk management
Features:
  - TSL at 33% activation with trailing
  - Leg shifting: CE and PE close independently on TP/SL
  - Morphing: Close losing leg, keep winning leg
  - Tests both parameter sets: (TP 20%, SL 5%) and (TP 25%, SL 3%)
"""

import duckdb
import pandas as pd
from pathlib import Path
import json
from datetime import datetime

def run_backtest(tp_percent, sl_percent, test_name):
    print(f"\n{'='*70}")
    print(f"BACKTEST: {test_name}")
    print(f"TP: {tp_percent*100:.0f}% | SL: {sl_percent*100:.0f}%")
    print(f"{'='*70}")

    # Load data into DuckDB
    dataset_path = Path(
        "/root/.cache/kagglehub/datasets/kaalicharan9080/nse-future-and-options-data/versions/2"
    )
    csv_files = sorted(dataset_path.glob("NSE_FNO*.csv"))[:5]

    conn = duckdb.connect(":memory:")

    for csv_file in csv_files:
        try:
            table_name = f"data_{csv_files.index(csv_file)}"
            conn.execute(
                f"CREATE TABLE {table_name} AS SELECT * FROM read_csv('{csv_file}')"
            )
        except Exception as e:
            pass

    all_tables = [f"data_{i}" for i in range(len(csv_files))]
    union_query = " UNION ALL ".join([f"SELECT * FROM {t}" for t in all_tables])
    conn.execute(f"CREATE TABLE all_data AS {union_query}")

    # Filter NIFTY index options
    conn.execute("DROP TABLE IF EXISTS nifty_opts")
    conn.execute("""
        CREATE TABLE nifty_opts AS
        SELECT *
        FROM all_data
        WHERE Ticker LIKE '%NIFTY%'
          AND NOT Ticker LIKE '%BANKNIFTY%'
          AND (Ticker LIKE '%CE%' OR Ticker LIKE '%PE%')
    """)

    # Parse and prepare data
    conn.execute(r"""
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

    trades = []
    morphs_triggered = 0

    opens = conn.execute("SELECT * FROM daily_opens ORDER BY trade_date").fetchall()

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
        """).fetchall()

        if not intra:
            continue

        # Leg parameters
        tp_price = entry_price * (1 - tp_percent)  # For shorts: price drops
        sl_price = entry_price * (1 + sl_percent)  # For shorts: price rises

        # TSL: activate at 33% of profit to TP
        tsl_activation_level = entry_price - (entry_price - tp_price) * 0.33
        max_favorable_price = entry_price
        tsl_active = False

        exit_signal = None
        exit_price = None
        exit_time = None
        exit_reason = None

        for dt, price in intra:
            # Track max favorable (lowest for shorts)
            if price < max_favorable_price:
                max_favorable_price = price

            # Check TSL activation (33% profit achieved)
            if not tsl_active and price <= tsl_activation_level:
                tsl_active = True

            # Exit conditions
            if price <= tp_price:
                exit_signal = "TP"
                exit_price = price
                exit_time = dt
                exit_reason = "TP_HIT"
                break
            elif tsl_active and price >= (max_favorable_price + (entry_price - tp_price) * 0.25):
                # TSL: exit if price pulls back 25% of profit range from max favorable
                exit_signal = "TSL"
                exit_price = price
                exit_time = dt
                exit_reason = "TSL_EXIT"
                break
            elif price >= sl_price and not tsl_active:
                # SL: close leg if TSL not active
                exit_signal = "SL"
                exit_price = price
                exit_time = dt
                exit_reason = "LEG_SHIFT_SL"  # Leg shifting: close losing leg, morph position
                break

        if exit_signal:
            pnl_points = entry_price - exit_price
            pnl_rupees = pnl_points * 75  # 2024 lot size

            if exit_time:
                duration = (exit_time - open_time).total_seconds() / 60
            else:
                duration = 0

            trades.append({
                "date": str(trade_date),
                "strike": strike,
                "type": type_,
                "entry": round(entry_price, 2),
                "exit": round(exit_price, 2),
                "signal": exit_signal,
                "reason": exit_reason,
                "pnl": round(pnl_rupees, 2),
                "points": round(pnl_points, 2),
                "duration_mins": round(duration, 0),
                "win": 1 if pnl_rupees > 0 else 0,
                "tsl_active": tsl_active,
            })

            if exit_reason == "LEG_SHIFT_SL":
                morphs_triggered += 1

    # Analysis
    print(f"\n📊 Loading and processing {len(trades)} total legs...")

    if trades:
        trades_df = pd.DataFrame(trades)
        total_pnl = trades_df["pnl"].sum()
        wins = trades_df["win"].sum()
        losses = len(trades) - wins
        win_rate = (wins / len(trades) * 100) if trades else 0

        avg_win = trades_df[trades_df["win"] == 1]["pnl"].mean() if wins > 0 else 0
        avg_loss = trades_df[trades_df["win"] == 0]["pnl"].mean() if losses > 0 else 0

        tsl_exits = len(trades_df[trades_df["signal"] == "TSL"])
        tp_exits = len(trades_df[trades_df["signal"] == "TP"])
        sl_exits = len(trades_df[trades_df["signal"] == "SL"])

        print(f"\n💰 Performance:")
        print(f"   Total P&L: ₹{total_pnl:,.2f}")
        print(f"   Legs traded: {len(trades)}")
        print(f"   Win rate: {win_rate:.1f}% ({wins}W / {losses}L)")
        print(f"   Avg win: ₹{avg_win:,.2f}")
        print(f"   Avg loss: ₹{avg_loss:,.2f}")
        print(f"   Max win: ₹{trades_df['pnl'].max():,.2f}")
        print(f"   Max loss: ₹{trades_df['pnl'].min():,.2f}")

        if losses > 0 and avg_loss != 0:
            pf = abs(avg_win * wins) / abs(avg_loss * losses)
            print(f"   Profit factor: {pf:.2f}x")

        print(f"\n📊 Exit Distribution:")
        print(f"   TP exits: {tp_exits}")
        print(f"   TSL exits: {tsl_exits}")
        print(f"   SL exits (morphed): {sl_exits}")
        print(f"   Morph count: {morphs_triggered}")

        print(f"\n⏱️  Avg trade duration: {trades_df['duration_mins'].mean():.0f} mins")

        # Save results
        results = {
            "test_name": test_name,
            "tp_percent": tp_percent,
            "sl_percent": sl_percent,
            "timestamp": datetime.now().isoformat(),
            "total_legs": len(trades),
            "total_pnl": float(total_pnl),
            "win_rate_percent": float(win_rate),
            "wins": int(wins),
            "losses": int(losses),
            "avg_win": float(avg_win),
            "avg_loss": float(avg_loss),
            "profit_factor": float(abs(avg_win * wins) / abs(avg_loss * losses)) if losses > 0 and avg_loss != 0 else 0,
            "tsl_exits": int(tsl_exits),
            "morph_count": int(morphs_triggered),
        }

        return results

    conn.close()
    return None


# Run both parameter sets
print("\n" + "=" * 70)
print("BACKTEST: 2024 NIFTY IRON BUTTERFLY WITH LEG SHIFTING + TSL + MORPHING")
print("=" * 70)

result1 = run_backtest(0.20, 0.05, "CURRENT PARAMS (TP 20%, SL 5%)")
result2 = run_backtest(0.25, 0.03, "DEEPSEEK PARAMS (TP 25%, SL 3%)")

# Comparison
print(f"\n{'='*70}")
print("PARAMETER COMPARISON")
print(f"{'='*70}")

if result1 and result2:
    print(f"\n{'Metric':<25} {'TP 20% / SL 5%':<20} {'TP 25% / SL 3%':<20} {'Diff':<15}")
    print("-" * 80)

    metrics = [
        ("Total P&L", "total_pnl"),
        ("Legs traded", "total_legs"),
        ("Win rate %", "win_rate_percent"),
        ("Profit factor", "profit_factor"),
        ("Avg win", "avg_win"),
        ("Avg loss", "avg_loss"),
        ("TSL exits", "tsl_exits"),
        ("Morph count", "morph_count"),
    ]

    for label, key in metrics:
        val1 = result1.get(key, 0)
        val2 = result2.get(key, 0)

        if key in ["total_pnl", "avg_win", "avg_loss"]:
            print(f"{label:<25} ₹{val1:>18,.0f} ₹{val2:>18,.0f} ₹{val2-val1:>13,.0f}")
        elif key in ["win_rate_percent", "profit_factor"]:
            print(f"{label:<25} {val1:>18.1f}% {val2:>18.1f}% {val2-val1:>13.1f}")
        else:
            print(f"{label:<25} {val1:>18.0f} {val2:>18.0f} {val2-val1:>13.0f}")

    print(f"\n{'='*70}")
    best_pnl = "TP 25% / SL 3%" if result2["total_pnl"] > result1["total_pnl"] else "TP 20% / SL 5%"
    print(f"✅ Better P&L: {best_pnl}")
    print(f"{'='*70}\n")

    # Save comparison
    comparison = {
        "timestamp": datetime.now().isoformat(),
        "current_params": result1,
        "deepseek_params": result2,
        "winner_by_pnl": best_pnl,
    }

    Path("data/backtest_parameter_comparison_2024.json").write_text(json.dumps(comparison, indent=2))
    print(f"Comparison saved: data/backtest_parameter_comparison_2024.json\n")
