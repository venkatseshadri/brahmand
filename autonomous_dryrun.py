#!/usr/bin/env python3
"""
Autonomous Dry-Run Engine — Brahmand MVC Live Market Test

Runs fully unattended during a market window (default 11:00-12:00 IST).
- Randomly picks 3-5 entry times
- At each entry: reads DuckDB for live NIFTY spot/ATM, builds Iron Butterfly
- Simulates fills using DuckDB option_snapshots LTP as fill price
- Risk Agent places mock SL/TP orders
- Picks random exit times (some SL hit, some TP hit, some random close)
- Calculates P&L at each exit using DuckDB LTP
- Post-Mortem Agent reviews all trades after the window closes
- Writes learnings to ChromaDB and daily_config.json

Usage:
    python autonomous_dryrun.py [--start HH:MM] [--end HH:MM] [--trades N]

Cron (runs Mon-Wed-Fri):
    0 11 * * 1,3,5 cd /home/trading_ceo/brahmand && python autonomous_dryrun.py >> logs/dryrun_$(date +%Y%m%d).log 2>&1
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from duckdb_tool import (
    MarketDataQueryTool,
    OptionSnapshotQueryTool,
    get_latest_market_snapshot,
)
from persistence import (
    init_db,
    save_execution_report,
    query_execution_reports,
    get_today_date_int,
)
from schemas import ExecutionReport

DUCKDB_VARAH_DATA = Path(
    "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"
)
LOG_DIR = Path(__file__).parent / "logs"

# ── Configuration ──────────────────────────────────────────────────────────

WINDOW_START = "11:00"
WINDOW_END = "12:00"
N_TRADES = random.randint(3, 5)
WING_WIDTH = 200  # points from ATM (overridden by e2e_chain Strategy Agent)
SL_PCT = 1.25  # premium * 1.25 (overridden by e2e_chain Strategy Agent)
TP_PCT = 0.50  # premium * 0.50 (overridden by e2e_chain Strategy Agent)
POLL_SECONDS = 60  # DuckDB refresh rate

# ── Helpers ────────────────────────────────────────────────────────────────


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    sys.stdout.flush()


def time_to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def now_minutes() -> int:
    return time_to_minutes(datetime.now().strftime("%H:%M"))


def sleep_until(target: str):
    """Sleep until HH:MM. If target is past, return immediately."""
    target_m = time_to_minutes(target)
    while now_minutes() < target_m:
        time.sleep(5)


def get_today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def duckdb_has_data() -> bool:
    return DUCKDB_VARAH_DATA.exists()


class DuckDBMarket:
    """Wraps DuckDB queries for live market data."""

    def __init__(self):
        self.market_tool = MarketDataQueryTool()
        self.option_tool = OptionSnapshotQueryTool()
        self.today = get_today_str()

    def latest_snapshot(self) -> dict:
        """Get the latest market snapshot from DuckDB."""
        snap = get_latest_market_snapshot()
        if not snap:
            return {}
        return {
            "spot": float(snap.get("spot", 0)),
            "atm_strike": int(float(snap.get("atm_strike", 0))),
            "vix": float(snap.get("india_vix", 0)),
            "adx": float(snap.get("adx", 0) or 0),
            "iv_current": float(snap.get("iv_current", 0)),
            "iv_rank": float(snap.get("iv_rank", 0)),
            "time": snap.get("time", ""),
            "date": snap.get("date", ""),
            "expiry_weekly": snap.get("expiry_weekly", ""),
        }

    def get_option_ltp(self, strike: int, option_type: str, expiry: str) -> float:
        """Get latest LTP for a specific option, filtered by expiry date + weekly label."""
        raw = self.option_tool._run(
            date=self.today,
            strike=strike,
            option_type=option_type,
            time_range="",
        )
        try:
            rows = json.loads(raw)
            if rows and isinstance(rows, list):
                for row in rows:
                    row_expiry = row.get("expiry_date", "")
                    row_label = row.get("expiry_label", "")
                    if expiry and row_expiry == expiry and row_label == "weekly":
                        return float(row.get("ltp", 0))
                # Fallback: first row matching expiry only
                for row in rows:
                    if expiry and row.get("expiry_date", "") == expiry:
                        return float(row.get("ltp", 0))
                return float(rows[0].get("ltp", 0)) if rows else 0.0
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
        return 0.0

    def get_atm_chain(
        self, atm_strike: int, expiry: str, wing_width: int = 200
    ) -> dict:
        """Get LTPs for all 4 legs of Iron Butterfly, all sharing the same expiry."""
        return {
            "center_ce": self.get_option_ltp(atm_strike, "CE", expiry),
            "center_pe": self.get_option_ltp(atm_strike, "PE", expiry),
            "wing_ce": self.get_option_ltp(atm_strike - wing_width, "CE", expiry),
            "wing_pe": self.get_option_ltp(atm_strike + wing_width, "PE", expiry),
        }


# ── Trade Simulator ────────────────────────────────────────────────────────


class TradeSimulator:
    """Simulates a single Iron Butterfly trade using DuckDB data."""

    def __init__(self, market: DuckDBMarket):
        self.market = market

    def enter_trade(
        self,
        entry_time: str,
        wing_width: int = None,
        sl_pct: float = None,
        tp_pct: float = None,
    ) -> dict:
        """
        Enter an Iron Butterfly at the current DuckDB snapshot.
        Returns trade dict with all legs, premiums, SL, TP.
        """
        ww = wing_width if wing_width is not None else WING_WIDTH
        sl = sl_pct if sl_pct is not None else SL_PCT
        tp = tp_pct if tp_pct is not None else TP_PCT

        snap = self.market.latest_snapshot()
        if not snap or snap.get("spot", 0) == 0:
            log("  ⚠ DuckDB snapshot empty — skipping entry")
            return {}

        spot = snap["spot"]
        atm = snap["atm_strike"]
        vix = snap["vix"]
        expiry = snap.get("expiry_weekly", "")

        prices = self.market.get_atm_chain(atm, expiry)
        if all(v == 0 for v in prices.values()):
            log("  ⚠ No option chain data in DuckDB — skipping entry")
            return {}

        premium_sell = prices["center_ce"] + prices["center_pe"]
        premium_buy = prices["wing_ce"] + prices["wing_pe"]
        net_credit = premium_sell - premium_buy

        sl_center_ce = round(prices["center_ce"] * SL_PCT, 2)
        sl_center_pe = round(prices["center_pe"] * SL_PCT, 2)
        tp_center_ce = round(prices["center_ce"] * TP_PCT, 2)
        tp_center_pe = round(prices["center_pe"] * TP_PCT, 2)

        trade = {
            "entry_time": entry_time,
            "spot_at_entry": spot,
            "atm_strike": atm,
            "vix": vix,
            "net_credit": round(net_credit, 2),
            "premium_sell": round(premium_sell, 2),
            "premium_buy": round(premium_buy, 2),
            "legs": [
                {
                    "action": "SELL",
                    "strike": atm,
                    "type": "CE",
                    "fill_price": prices["center_ce"],
                },
                {
                    "action": "SELL",
                    "strike": atm,
                    "type": "PE",
                    "fill_price": prices["center_pe"],
                },
                {
                    "action": "BUY",
                    "strike": atm - WING_WIDTH,
                    "type": "CE",
                    "fill_price": prices["wing_ce"],
                },
                {
                    "action": "BUY",
                    "strike": atm + WING_WIDTH,
                    "type": "PE",
                    "fill_price": prices["wing_pe"],
                },
            ],
            "sl": {"ce": sl_center_ce, "pe": sl_center_pe},
            "tp": {"ce": tp_center_ce, "pe": tp_center_pe},
            "status": "OPEN",
        }

        # Write to state.db
        for leg in trade["legs"]:
            if leg["action"] == "SELL":
                oid = f"SIM-{get_today_str().replace('-', '')}-{leg['type']}{leg['strike']}"
                save_execution_report(
                    ExecutionReport(
                        order_id=oid,
                        status="MOCK",
                        fill_price=leg["fill_price"],
                        agent_version="autonomous-dryrun",
                    )
                )

        return trade

    def exit_trade(self, trade: dict, exit_time: str) -> dict:
        """
        Close a trade at the current DuckDB LTP for each SELL leg.
        Returns trade dict with P&L calculated.
        """
        atm = trade["atm_strike"]
        expiry = trade.get("expiry", "")
        prices = {
            "center_ce": self.market.get_option_ltp(atm, "CE", expiry),
            "center_pe": self.market.get_option_ltp(atm, "PE", expiry),
        }

        pnl_ce = trade["legs"][0]["fill_price"] - prices["center_ce"]
        pnl_pe = trade["legs"][1]["fill_price"] - prices["center_pe"]
        total_pnl = round(pnl_ce + pnl_pe, 2)

        trade["exit_time"] = exit_time
        trade["exit_prices"] = prices
        trade["pnl"] = total_pnl
        trade["pnl_ce"] = round(pnl_ce, 2)
        trade["pnl_pe"] = round(pnl_pe, 2)
        trade["status"] = "CLOSED"

        # Determine exit reason
        if trade["entry_time"] == exit_time:
            trade["exit_reason"] = "ENDPIPE"
        elif total_pnl <= -(trade["net_credit"] * 0.25):
            trade["exit_reason"] = "SL_HIT"
        elif total_pnl >= (trade["net_credit"] * 0.50):
            trade["exit_reason"] = "TP_HIT"
        else:
            trade["exit_reason"] = "RANDOM_CLOSE"

        return trade


# ── Post-Mortem Runner ─────────────────────────────────────────────────────


def run_post_mortem(trades_log: list[dict]):
    """After all trades close, run Post-Mortem to analyze and write ChromaDB."""
    log("\\n=== POST-MORTEM ANALYSIS ===")

    from chromadb_tool import store_research_note
    from factory import AgentFactory
    from chromadb_tool import QueryChromaDBTool, StoreResearchNoteTool
    from duckdb_tool import MarketDataQueryTool as MDQ, OptionSnapshotQueryTool as OSQ
    from crewai import Agent, Task, Crew, Process, LLM

    today_int = get_today_date_int()

    # Seed today's ChromaDB with trades summary
    summary = json.dumps(trades_log, default=str, indent=2)

    af = AgentFactory()
    pm = af.create_agent(
        "postmortem_agent",
        {"today_date_int": today_int, "chroma_collection": "brahmand_notes"},
        tools=[QueryChromaDBTool(), StoreResearchNoteTool(), MDQ(), OSQ()],
    )
    pm.llm = LLM(
        model="deepseek/deepseek-chat",
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
    )

    task = Task(
        description=f"""POST-MORTEM for autonomous dry-run session.

Date: {today_int}
Window: {WINDOW_START} - {WINDOW_END} IST
Strategy: IRON_BUTTERFLY, ATM +/-{WING_WIDTH} wings
Trades executed: {len(trades_log)}

ALL TRADES:
{summary}

Analyze:
1. Which exits were optimal? Which left money on the table? Which prevented loss?
2. Cross-reference with DuckDB market data (VIX, ADX, IV rank at entry times)
3. Did entry timing matter? Were later entries better?
4. Were exits that happened early (random close) better or worse than SL/TP-based exits?
5. Write specific observations + suggested actions to ChromaDB
6. Generate daily_config.json updates for next session

Output JSON research notes.""",
        expected_output="Post-Mortem research notes JSON",
        agent=pm,
    )

    try:
        crew = Crew(
            agents=[pm], tasks=[task], process=Process.sequential, verbose=False
        )
        result = crew.kickoff()
        log(f"  Post-Mortem output: {str(result)[:300]}...")
    except Exception as e:
        log(f"  ⚠ Post-Mortem failed: {e}")
        log(f"  Raw trades saved to logs/trades_{today_int}.json")
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR / f"trades_{today_int}.json").write_text(summary)


# ── Main Orchestrator ──────────────────────────────────────────────────────


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    if not duckdb_has_data():
        log("❌ DuckDB not found. Exiting.")
        sys.exit(1)

    market = DuckDBMarket()
    snap = market.latest_snapshot()
    if not snap or snap.get("spot", 0) == 0:
        log("❌ DuckDB has no data. Is varaha pipeline running? Exiting.")
        sys.exit(1)

    log(
        f"DuckDB ready — spot={snap['spot']}, ATM={snap['atm_strike']}, VIX={snap['vix']}"
    )
    log(
        f"Window: {WINDOW_START}-{WINDOW_END} | Trades: {N_TRADES} | Wing width: {WING_WIDTH}"
    )

    # Generate random entry/exit times
    start_m = time_to_minutes(WINDOW_START) + random.randint(2, 5)
    end_m = time_to_minutes(WINDOW_END) - random.randint(3, 8)

    entry_times = sorted(
        start_m
        + random.randint(0, (end_m - start_m - 5) // N_TRADES) * i
        + random.randint(1, 4)
        for i in range(N_TRADES)
    )

    def fmt(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    entry_times_str = [fmt(m) for m in entry_times]
    exit_times_str = []
    for i, m in enumerate(entry_times):
        next_entry = entry_times[i + 1] if i + 1 < len(entry_times) else end_m
        exit_m = m + random.randint(5, max(5, next_entry - m - 3))
        exit_times_str.append(fmt(exit_m))

    log(f"Entry times: {entry_times_str}")
    log(f"Exit times:  {exit_times_str}")

    # Wait for window start
    log(f"\\nWaiting for {WINDOW_START}...")
    sleep_until(WINDOW_START)
    log("=== DRY-RUN SESSION STARTED ===")

    all_trades = []

    for i, entry_t in enumerate(entry_times_str):
        sleep_until(entry_t)
        log(f"\n[{entry_t}] Trade {i + 1}/{N_TRADES} — ENTRY")

        # ── E2E Chain: Regime → Strategy → Contract → Execution → Risk ─────
        from e2e_chain import run_full_chain

        trade = run_full_chain(entry_t)
        if not trade:
            continue

        # Wait for exit time
        exit_t = exit_times_str[i]
        sleep_until(exit_t)

        # Check if SL or TP crossed before planned exit
        # Poll DuckDB every minute between entry and exit to check conditions
        check_t = time_to_minutes(entry_t)
        exit_m = time_to_minutes(exit_t)
        forced_exit = False
        sl_hit_time = None
        tp_hit_time = None

        while check_t < exit_m and not forced_exit:
            check_t += 1
            time.sleep(POLL_SECONDS)

            # Check current LTPs for each SELL leg
            expiry = trade.get("expiry", "")
            hit = False
            for leg in trade["legs"]:
                if leg["action"] != "SELL":
                    continue
                t = leg["type"].lower()
                ltp = market.get_option_ltp(leg["strike"], leg["type"], expiry)

                if ltp > 0 and trade["sl"].get(t) and ltp >= trade["sl"][t]:
                    log(
                        f"  [{fmt(check_t)}] SL HIT — {leg['tsym']}: LTP={ltp} >= SL={trade['sl'][t]}"
                    )
                    sl_hit_time = fmt(check_t)
                    hit = True
                elif ltp > 0 and trade["tp"].get(t) and ltp <= trade["tp"][t]:
                    log(
                        f"  [{fmt(check_t)}] TP HIT — {leg['tsym']}: LTP={ltp} <= TP={trade['tp'][t]}"
                    )
                    tp_hit_time = fmt(check_t)
                    hit = True
            if hit:
                forced_exit = True

        actual_exit = sl_hit_time or tp_hit_time or exit_t

        # Calculate P&L from DuckDB LTP at exit for each SELL leg
        expiry = trade.get("expiry", "")
        total_pnl = 0.0
        for leg in trade["legs"]:
            if leg["action"] == "SELL":
                exit_ltp = market.get_option_ltp(leg["strike"], leg["type"], expiry)
                total_pnl += leg["fill_price"] - exit_ltp

        trade["exit_time"] = actual_exit
        trade["pnl"] = round(total_pnl, 2)
        trade["status"] = "CLOSED"

        if sl_hit_time:
            trade["exit_reason"] = "SL_HIT"
        elif tp_hit_time:
            trade["exit_reason"] = "TP_HIT"
        else:
            trade["exit_reason"] = "RANDOM_CLOSE"

        log(f"  [{actual_exit}] EXIT ({trade['exit_reason']}) — P&L: ₹{trade['pnl']}")

        all_trades.append(trade)
        time.sleep(random.randint(10, 30))

    log(f"\\nSession ended. {len(all_trades)}/{N_TRADES} trades completed.")

    # Calculate session stats
    if all_trades:
        total_pnl = sum(t["pnl"] for t in all_trades)
        wins = sum(1 for t in all_trades if t["pnl"] > 0)
        losses = sum(1 for t in all_trades if t["pnl"] < 0)
        reasons = {}
        for t in all_trades:
            reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
        log(f"Total P&L: ₹{total_pnl} | Wins: {wins} | Losses: {losses}")
        log(f"Exit reasons: {reasons}")

    # Save trades to JSON log
    trades_file = LOG_DIR / f"trades_{get_today_str().replace('-', '')}.json"
    trades_file.write_text(
        json.dumps(
            {
                "trades": all_trades,
                "total_pnl": total_pnl if all_trades else 0,
                "wins": wins if all_trades else 0,
                "losses": losses if all_trades else 0,
            },
            indent=2,
            default=str,
        )
    )
    log(f"Trades saved: {trades_file}")

    # Run Post-Mortem
    if all_trades:
        run_post_mortem(all_trades)

    log("\\n=== DRY-RUN COMPLETE ===")


if __name__ == "__main__":
    main()
