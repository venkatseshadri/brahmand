#!/usr/bin/env python3
"""
Backtest 2024 NIFTY Butterflies WITH Leg Shifting Simulation

Tests the actual mechanics of leg shifting:
- When HEDGE decays 50%, shift to new strike closer to SELL (narrower wing)
- When SELL decays 60%, shift to new strike farther from HEDGE (wider wing)
- Track P&L impact of shifts vs no-shifts

Key insight: Shifts only work when price is STABLE (theta decay dominant).
When price moves against position, shifts don't help.
"""

import duckdb
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

DB_PATH = "/home/trading_ceo/projects/brahmand/data/nifty_options_2024.duckdb"

def query_option_price_at_date(conn: duckdb.DuckDBPyConnection, symbol: str, date: str) -> Optional[float]:
    """Query option price for a given date."""
    query = f"""
    SELECT closing_price FROM nifty_options_table
    WHERE symbol = '{symbol}' AND date = '{date}'
    LIMIT 1
    """
    try:
        result = conn.execute(query).fetchall()
        return float(result[0][0]) if result else None
    except:
        return None


def calculate_decay_percentage(entry_price: float, current_price: float) -> float:
    """Calculate % decay from entry price."""
    if entry_price <= 0:
        return 0.0
    return ((entry_price - current_price) / entry_price) * 100


def simulate_butterfly_with_shifts(
    conn: duckdb.DuckDBPyConnection,
    entry_date: str,
    expiry_date: str,
    atm_strike: int,
    sell_strike: int,
    hedge_strike: int,
    entry_credit: float,
    tp_pct: float = 0.20,
    sl_pct: float = 0.05,
) -> Dict:
    """
    Simulate a single butterfly with leg shifting.

    Returns: {
        'entry_date': str,
        'pnl_no_shift': float,
        'pnl_with_shifts': float,
        'shifts_executed': [list of shift events],
        'reason_close': str (TP/SL/Expiry/Shift_failed),
    }
    """

    lot_size = 75

    # Initial position
    position = {
        'sell_strike': sell_strike,
        'sell_price': None,  # Will fetch
        'hedge_strike': hedge_strike,
        'hedge_price': None,  # Will fetch
        'sell_qty': lot_size,
        'hedge_qty': lot_size,
    }

    # Fetch entry prices
    sell_symbol = f"NIFTY{entry_date.split('-')[0]}{entry_date.split('-')[1]}{entry_date.split('-')[2]}{sell_strike}PE"
    hedge_symbol = f"NIFTY{entry_date.split('-')[0]}{entry_date.split('-')[1]}{entry_date.split('-')[2]}{hedge_strike}PE"

    position['sell_price'] = query_option_price_at_date(conn, sell_symbol, entry_date)
    position['hedge_price'] = query_option_price_at_date(conn, hedge_symbol, entry_date)

    if not position['sell_price'] or not position['hedge_price']:
        return {
            'entry_date': entry_date,
            'pnl_no_shift': 0,
            'pnl_with_shifts': 0,
            'shifts_executed': [],
            'reason_close': 'DATA_MISSING'
        }

    # Calculate P&L thresholds
    entry_spread = position['sell_price'] - position['hedge_price']
    tp_close = entry_spread * (1 - tp_pct)
    sl_close = entry_spread * (1 + sl_pct)

    pnl_no_shift = 0
    pnl_with_shifts = 0
    shifts_executed = []
    close_reason = "EXPIRY"

    # Iterate through dates until expiry
    current_date = entry_date
    start_dt = datetime.strptime(entry_date, "%Y-%m-%d")
    expiry_dt = datetime.strptime(expiry_date, "%Y-%m-%d")

    while current_date <= expiry_date:
        # Query current prices
        sell_symbol = f"NIFTY{current_date.split('-')[0]}{current_date.split('-')[1]}{current_date.split('-')[2]}{position['sell_strike']}PE"
        hedge_symbol = f"NIFTY{current_date.split('-')[0]}{current_date.split('-')[1]}{current_date.split('-')[2]}{position['hedge_strike']}PE"

        current_sell_price = query_option_price_at_date(conn, sell_symbol, current_date)
        current_hedge_price = query_option_price_at_date(conn, hedge_symbol, current_date)

        if not current_sell_price or not current_hedge_price:
            # No data for this date, move to next
            current_date = (datetime.strptime(current_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            continue

        # --- SCENARIO 1: NO SHIFTS ---
        current_spread_no_shift = current_sell_price - current_hedge_price

        if current_spread_no_shift <= tp_close:
            pnl_no_shift = (entry_spread - current_spread_no_shift) * lot_size
            close_reason = "TP_HIT"
            break

        if current_spread_no_shift >= sl_close:
            pnl_no_shift = (entry_spread - current_spread_no_shift) * lot_size
            close_reason = "SL_HIT"
            break

        # --- SCENARIO 2: WITH LEG SHIFTS ---
        # Check if HEDGE should shift (50% decay)
        hedge_decay = calculate_decay_percentage(position['hedge_price'], current_hedge_price)
        if hedge_decay >= 50 and position['hedge_strike'] < position['sell_strike']:
            new_hedge_strike = position['hedge_strike'] + 50  # Shift closer to SELL
            new_hedge_symbol = f"NIFTY{current_date.split('-')[0]}{current_date.split('-')[1]}{current_date.split('-')[2]}{new_hedge_strike}PE"
            new_hedge_price = query_option_price_at_date(conn, new_hedge_symbol, current_date)

            if new_hedge_price:
                # Shift: close old hedge, buy new hedge
                shifts_executed.append({
                    'date': current_date,
                    'type': 'HEDGE_SHIFT',
                    'from_strike': position['hedge_strike'],
                    'to_strike': new_hedge_strike,
                    'old_price': current_hedge_price,
                    'new_price': new_hedge_price,
                    'cost': (new_hedge_price - current_hedge_price) * lot_size,
                })
                position['hedge_strike'] = new_hedge_strike
                position['hedge_price'] = new_hedge_price

        # Check if SELL should shift (60% decay) — moves farther from ATM
        sell_decay = calculate_decay_percentage(position['sell_price'], current_sell_price)
        if sell_decay >= 60 and position['sell_strike'] < position['hedge_strike']:
            new_sell_strike = position['sell_strike'] + 50  # Move farther from HEDGE
            new_sell_symbol = f"NIFTY{current_date.split('-')[0]}{current_date.split('-')[1]}{current_date.split('-')[2]}{new_sell_strike}PE"
            new_sell_price = query_option_price_at_date(conn, new_sell_symbol, current_date)

            if new_sell_price:
                # Shift: close old sell, sell new sell
                shifts_executed.append({
                    'date': current_date,
                    'type': 'SELL_SHIFT',
                    'from_strike': position['sell_strike'],
                    'to_strike': new_sell_strike,
                    'old_price': current_sell_price,
                    'new_price': new_sell_price,
                    'credit': (current_sell_price - new_sell_price) * lot_size,
                })
                position['sell_strike'] = new_sell_strike
                position['sell_price'] = new_sell_price

        # Check exit conditions
        current_spread_with_shifts = position['sell_price'] - position['hedge_price']

        if current_spread_with_shifts <= tp_close:
            # P&L = (original entry - current close) * lot - shift costs
            pnl_with_shifts = (entry_spread - current_spread_with_shifts) * lot_size
            for shift in shifts_executed:
                if shift['type'] == 'HEDGE_SHIFT':
                    pnl_with_shifts -= shift['cost']
                elif shift['type'] == 'SELL_SHIFT':
                    pnl_with_shifts += shift['credit']
            close_reason = "TP_HIT"
            break

        if current_spread_with_shifts >= sl_close:
            pnl_with_shifts = (entry_spread - current_spread_with_shifts) * lot_size
            for shift in shifts_executed:
                if shift['type'] == 'HEDGE_SHIFT':
                    pnl_with_shifts -= shift['cost']
                elif shift['type'] == 'SELL_SHIFT':
                    pnl_with_shifts += shift['credit']
            close_reason = "SL_HIT"
            break

        # Move to next date
        current_date = (datetime.strptime(current_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    # At expiry
    if current_date == expiry_date:
        pnl_no_shift = (entry_spread - (current_sell_price - current_hedge_price)) * lot_size
        pnl_with_shifts = pnl_no_shift
        for shift in shifts_executed:
            if shift['type'] == 'HEDGE_SHIFT':
                pnl_with_shifts -= shift['cost']
            elif shift['type'] == 'SELL_SHIFT':
                pnl_with_shifts += shift['credit']

    return {
        'entry_date': entry_date,
        'sell_strike': position['sell_strike'],
        'hedge_strike': position['hedge_strike'],
        'entry_spread': entry_spread,
        'pnl_no_shift': pnl_no_shift,
        'pnl_with_shifts': pnl_with_shifts,
        'shift_impact': pnl_with_shifts - pnl_no_shift,
        'shifts_count': len(shifts_executed),
        'shifts_executed': shifts_executed,
        'reason_close': close_reason,
    }


def main():
    """Run backtest with leg shifting."""
    try:
        conn = duckdb.connect(DB_PATH, read_only=True)

        print("\n" + "="*140)
        print("2024 NIFTY BUTTERFLY BACKTEST WITH LEG SHIFTING SIMULATION")
        print("="*140)

        # Run a small sample
        sample_trades = [
            {
                'entry_date': '2024-01-05',
                'expiry_date': '2024-01-11',
                'atm': 21700,
                'sell': 21700,
                'hedge': 21500,
                'entry_credit': 75.0,
            },
            {
                'entry_date': '2024-01-22',
                'expiry_date': '2024-01-25',
                'atm': 21900,
                'sell': 21900,
                'hedge': 21700,
                'entry_credit': 80.0,
            },
        ]

        results = []
        for trade in sample_trades:
            result = simulate_butterfly_with_shifts(
                conn,
                trade['entry_date'],
                trade['expiry_date'],
                trade['atm'],
                trade['sell'],
                trade['hedge'],
                trade['entry_credit'],
            )
            results.append(result)

            print(f"\n📊 {result['entry_date']}")
            print(f"   Entry: SELL {trade['sell']} / BUY {trade['hedge']} (spread ₹{result['entry_spread']:.0f})")
            print(f"   P&L (No shifts): ₹{result['pnl_no_shift']:,.0f}")
            print(f"   P&L (With shifts): ₹{result['pnl_with_shifts']:,.0f}")
            print(f"   Shift impact: ₹{result['shift_impact']:+,.0f} ({result['shifts_count']} shifts)")
            print(f"   Reason close: {result['reason_close']}")

            if result['shifts_executed']:
                print(f"   Shifts executed:")
                for shift in result['shifts_executed']:
                    print(f"     - {shift['date']}: {shift['type']} ({shift['from_strike']}→{shift['to_strike']})")

        # Summary
        print(f"\n{'='*140}")
        print("SUMMARY")
        print(f"{'='*140}\n")

        total_no_shift = sum(r['pnl_no_shift'] for r in results)
        total_with_shift = sum(r['pnl_with_shifts'] for r in results)
        total_shift_impact = total_with_shift - total_no_shift

        print(f"Total P&L (No shifts): ₹{total_no_shift:,.0f}")
        print(f"Total P&L (With shifts): ₹{total_with_shift:,.0f}")
        print(f"Total shift impact: ₹{total_shift_impact:+,.0f}")
        print(f"Shift win rate: {len([r for r in results if r['shift_impact'] > 0])}/{len(results)}")

        # Save results
        output_path = Path("/home/trading_ceo/projects/brahmand/data/backtest_2024_leg_shift_results.json")
        output_path.write_text(json.dumps({
            'timestamp': datetime.now().isoformat(),
            'sample_size': len(results),
            'total_pnl_no_shift': total_no_shift,
            'total_pnl_with_shift': total_with_shift,
            'total_shift_impact': total_shift_impact,
            'results': results,
        }, indent=2, default=str))

        print(f"\n✅ Results saved: data/backtest_2024_leg_shift_results.json\n")

    except Exception as e:
        print(f"❌ Backtest error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
