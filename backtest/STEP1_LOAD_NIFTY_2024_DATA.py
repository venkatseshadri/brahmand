#!/usr/bin/env python3
"""
STEP 1: Load & Parse NIFTY 2024 Data from Kaggle Cache

Purpose: Extract NIFTY option data and build market snapshots ready for agent tools.
Source: /root/.cache/kagglehub/datasets/kaalicharan9080/nse-future-and-options-data/versions/2/

Output: Market snapshots with:
- date, spot_price, atm_strike
- option premiums (SELL/BUY for 200pt butterfly wing)
- entry_spread = SELL_premium - BUY_premium
- Ready for agent tools (score_trend_redis, score_traffic_light_redis)
"""

import csv
import json
import os
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Optional
import re


class NIFTY2024DataLoader:
    """Load and parse NIFTY 2024 data from kaggle cache."""

    def __init__(self):
        self.kaggle_cache = Path(
            "/root/.cache/kagglehub/datasets/kaalicharan9080/nse-future-and-options-data/versions/2"
        )
        self.data = defaultdict(lambda: defaultdict(list))
        self.market_snapshots = []

    def load_csv_file(self, csv_file: Path) -> None:
        """Load a single CSV file and extract NIFTY data."""
        print(f"  📖 Loading {csv_file.name}...", end=" ", flush=True)

        with open(csv_file) as f:
            reader = csv.reader(f)
            count = 0
            for ticker, date, time, open_p, high, low, close, vol, oi in reader:
                if ticker.startswith("NIFTY") and "OCT24" in ticker:
                    # Extract strike: NIFTY24OCT2423500PE.NFO → 23500, PE
                    match = re.search(r"(\d{5})(PE|CE)\.NFO", ticker)
                    if match:
                        strike = int(match.group(1))
                        opt_type = match.group(2)

                        # Store data by (date, time, strike, type)
                        self.data[date][f"{strike}{opt_type}"].append(
                            {
                                "time": time,
                                "open": float(open_p),
                                "high": float(high),
                                "low": float(low),
                                "close": float(close),
                                "volume": int(vol),
                                "oi": int(oi),
                            }
                        )
                        count += 1

        print(f"✓ {count:,} NIFTY records")

    def load_all_files(self) -> None:
        """Load all CSV files from kaggle cache."""
        import resource

        csv_files = set()
        for pat in ["NSE_FNO_DATA_2024-10-*.csv", "NSE_FNO_DATA_2024-10-*.CSV"]:
            csv_files.update(self.kaggle_cache.glob(pat))
        csv_files = sorted(csv_files, key=lambda f: f.name)
        print(f"\n📂 Found {len(csv_files)} CSV files in kaggle cache")
        print(f"   Files: {', '.join(f.name for f in csv_files)}\n")

        for csv_file in csv_files:
            self.load_csv_file(csv_file)

        # Memory budget
        mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        total_records = sum(
            len(records)
            for date_data in self.data.values()
            for records in date_data.values()
        )
        print(f"\n💾 Memory: {mem_mb:.0f} MB | Records: {total_records:,}\n")

    def find_atm_strike(self, date: str) -> Optional[int]:
        """Find ATM strike using highest combined CE+PE volume."""
        date_data = self.data[date]
        best_vol = -1
        best_strike = None
        for key, records in date_data.items():
            if not key.endswith("CE"):
                continue
            strike = int(key[:-2])
            pe_key = f"{strike}PE"
            if pe_key not in date_data:
                continue
            ce_vol = sum(r.get("volume", 0) for r in records[-5:])
            pe_records = date_data[pe_key]
            pe_vol = sum(r.get("volume", 0) for r in pe_records[-5:])
            total_vol = ce_vol + pe_vol
            if total_vol > best_vol:
                best_vol = total_vol
                best_strike = strike
        return best_strike

    def derive_spot_from_atm(self, date: str, atm_strike: int) -> Optional[float]:
        """
        Derive NIFTY spot price from ATM option prices.
        Uses call-put parity: spot ≈ (CE_price - PE_price) + strike
        """
        date_data = self.data[date]

        ce_key = f"{atm_strike}CE"
        pe_key = f"{atm_strike}PE"

        if ce_key in date_data and pe_key in date_data:
            ce_price = date_data[ce_key][-1]["close"]  # Latest close
            pe_price = date_data[pe_key][-1]["close"]
            spot = (ce_price - pe_price) + atm_strike
            return spot

        return None

    def get_option_premium(
        self, date: str, strike: int, opt_type: str, time_filter: str = None
    ) -> float:
        """Get option premium (close price) at a specific time or latest available."""
        date_data = self.data[date]
        key = f"{strike}{opt_type}"

        if key not in date_data:
            return None

        records = date_data[key]

        if time_filter == "market_open":
            # Get 09:15 or earliest record
            for r in records:
                if "09:15" in r["time"]:
                    return r["close"]
            return records[0]["close"] if records else None
        else:
            # Latest close
            return records[-1]["close"] if records else None

    def build_market_snapshot(
        self, date: str, time_filter: str = "market_open", direction: str = "PUT_SPREAD"
    ) -> Optional[dict]:
        """Build a market snapshot for a given date."""
        date_data = self.data[date]

        if not date_data:
            return None

        atm_strike = self.find_atm_strike(date)
        if atm_strike is None:
            atm_strike = 23500
            for strike in range(23000, 24500, 50):
                if f"{strike}CE" in date_data and f"{strike}PE" in date_data:
                    atm_strike = strike
                    break

        spot = self.derive_spot_from_atm(date, atm_strike)
        if spot is None:
            return None

        if direction == "CALL_SPREAD":
            sell_type, buy_type = "CE", "CE"
            wing_offset = 200
        else:
            sell_type, buy_type = "PE", "PE"
            wing_offset = -200

        sell_strike = atm_strike
        buy_strike = atm_strike + wing_offset

        sell_prem = self.get_option_premium(date, sell_strike, sell_type, time_filter)
        buy_prem = self.get_option_premium(date, buy_strike, buy_type, time_filter)

        if sell_prem is None or buy_prem is None:
            return None

        entry_spread = sell_prem - buy_prem

        first_time = min(
            (r[0]["time"] for r in date_data.values() if r),
            default="09:15:59",
        )

        snapshot = {
            "date": date,
            "time": first_time or "09:15:59",
            "spot": round(spot, 2),
            "atm_strike": atm_strike,
            "sell_strike": sell_strike,
            "buy_strike": buy_strike,
            "sell_premium": round(sell_prem, 2),
            "buy_premium": round(buy_prem, 2),
            "entry_spread": round(entry_spread, 2),
            "tp_target": round(entry_spread * 0.8, 2),
            "sl_target": round(entry_spread * 1.05, 2),
            "lot_size": 75,
            "tp_pnl": round((entry_spread - entry_spread * 0.8) * 75, 0),
            "sl_loss": round((entry_spread - entry_spread * 1.05) * 75, 0),
            "data_status": "ready_for_agents",
        }

        return snapshot

    def generate_all_snapshots(self) -> list:
        """Generate market snapshots for all dates."""
        print("\n🔄 Building market snapshots...\n")

        for date in sorted(self.data.keys()):
            snapshot = self.build_market_snapshot(date)
            if snapshot:
                self.market_snapshots.append(snapshot)
                print(
                    f"  ✓ {snapshot['date']} | SPOT ₹{snapshot['spot']:,.0f} | "
                    f"SELL {snapshot['sell_strike']} @ ₹{snapshot['sell_premium']:.2f} | "
                    f"BUY {snapshot['buy_strike']} @ ₹{snapshot['buy_premium']:.2f} | "
                    f"Spread ₹{snapshot['entry_spread']:.2f}"
                )

        return self.market_snapshots

    def save_snapshots(self, output_path: Path = None) -> Path:
        """Save market snapshots to JSON."""
        if output_path is None:
            output_path = Path(
                "/home/trading_ceo/brahmand/data/STEP1_NIFTY_2024_MARKET_SNAPSHOTS.json"
            )

        output = {
            "timestamp": datetime.now().isoformat(),
            "source": "Kaggle NSE FNO cache",
            "dates_processed": len(self.market_snapshots),
            "snapshots": self.market_snapshots,
        }

        output_path.write_text(json.dumps(output, indent=2))
        return output_path


def main():
    """Main execution."""
    print("\n" + "=" * 120)
    print("STEP 1: LOAD & PARSE NIFTY 2024 DATA FROM KAGGLE CACHE")
    print("=" * 120)

    loader = NIFTY2024DataLoader()

    # Load all CSV files
    loader.load_all_files()

    # Build snapshots
    snapshots = loader.generate_all_snapshots()

    # Save to JSON
    output_file = loader.save_snapshots()

    # Summary
    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120 + "\n")

    print(f"✅ Total market snapshots created: {len(snapshots)}")
    print(f"✅ Date range: {snapshots[0]['date']} to {snapshots[-1]['date']}")
    print(f"✅ Output file: {output_file}")
    print(f"\n📊 SNAPSHOT STRUCTURE (ready for agent tools):")
    print(json.dumps(snapshots[0], indent=2))

    print(f"\n✅ STEP 1 COMPLETE")
    print(f"   All data is traceable: date, spot, strike, premium, spread")
    print(
        f"   Next: Run through agent tools (score_trend_redis, score_traffic_light_redis)"
    )
    print(f"   Then: Apply NOT_UP/NOT_DOWN logic + entry gate filter\n")


if __name__ == "__main__":
    main()
