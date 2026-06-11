#!/usr/bin/env python3
"""SHERPA Phase 2 — spread lifecycle simulator with honest costs.

Executes what canonical_strategy decides: CALL_SPREAD (sell ATM CE / buy
ATM+wing CE) or PUT_SPREAD (sell ATM PE / buy ATM−wing PE), then manages it
per-minute with the canonical SL/TP params and an EOD square-off (intraday
system — live has the EOD cleanup backstop).
"""

from dataclasses import dataclass, field
from datetime import datetime

from . import bs_pricer

LOT_SIZE = 65          # current NIFTY lot (structural backtest: today's spec)
STRIKE_STEP = 50

# ── Honest cost model (constants explicit for the Board report) ─────────────
BROKERAGE_PER_ORDER = 20.0     # flat per executed order (4 orders/round trip)
SLIPPAGE_TICKS = 1             # ticks lost per fill per leg
TICK = 0.05
SLIPPAGE_PCT = 0.0025          # +0.25% of leg premium per fill (spread crossing)
STAT_CHARGES_PCT = 0.0007      # STT(sell)+exchange+SEBI+stamp+GST lump on premium turnover


@dataclass
class Trade:
    entry_ts: datetime
    strategy: str               # CALL_SPREAD | PUT_SPREAD
    sell_strike: int
    buy_strike: int
    opt_type: str               # CE | PE
    sell_entry: float
    buy_entry: float
    lots: int
    sl_pct: float
    tp_pct: float
    exit_ts: datetime = None
    exit_reason: str = ""
    sell_exit: float = 0.0
    buy_exit: float = 0.0
    costs: float = 0.0
    pnl: float = 0.0            # net of costs

    @property
    def qty(self) -> int:
        return self.lots * LOT_SIZE

    @property
    def net_credit(self) -> float:
        return self.sell_entry - self.buy_entry

    @property
    def max_loss_per_lot(self) -> float:
        wing = abs(self.buy_strike - self.sell_strike)
        return (wing - self.net_credit) * LOT_SIZE


def atm_strike(spot: float) -> int:
    return int(round(spot / STRIKE_STEP) * STRIKE_STEP)


def open_trade(decision: dict, spot: float, ts: datetime, vix: float, lots: int) -> Trade | None:
    strat = decision["strategy"]["strategy_type"]
    wing = decision["strategy"]["wing_width"]
    atm = atm_strike(spot)
    if strat == "CALL_SPREAD":
        opt, sell_k, buy_k = "CE", atm, atm + wing
    elif strat == "PUT_SPREAD":
        opt, sell_k, buy_k = "PE", atm, atm - wing
    else:
        return None
    sell_px = bs_pricer.price_leg(spot, sell_k, opt, ts, vix)
    buy_px = bs_pricer.price_leg(spot, buy_k, opt, ts, vix)
    if sell_px <= buy_px or sell_px <= 1.0:
        return None  # no real credit at this vol/time — refuse the entry
    # fills cross the spread against us
    sell_fill = sell_px - (SLIPPAGE_TICKS * TICK + sell_px * SLIPPAGE_PCT)
    buy_fill = buy_px + (SLIPPAGE_TICKS * TICK + buy_px * SLIPPAGE_PCT)
    return Trade(
        entry_ts=ts,
        strategy=strat,
        sell_strike=sell_k,
        buy_strike=buy_k,
        opt_type=opt,
        sell_entry=round(sell_fill, 2),
        buy_entry=round(buy_fill, 2),
        lots=lots,
        sl_pct=decision["strategy"]["sl_pct"],
        tp_pct=decision["strategy"]["tp_pct"],
    )


def mark(trade: Trade, spot: float, ts: datetime, vix: float) -> tuple[float, float]:
    sell_px = bs_pricer.price_leg(spot, trade.sell_strike, trade.opt_type, ts, vix)
    buy_px = bs_pricer.price_leg(spot, trade.buy_strike, trade.opt_type, ts, vix)
    return sell_px, buy_px


def check_exit(trade: Trade, sell_px: float, hhmm: str, eod_hhmm: str = "15:25") -> str:
    """Same exit semantics the live position_manager applies to the sold leg."""
    if sell_px >= trade.sell_entry * (1 + trade.sl_pct):
        return "SL_HIT"
    if sell_px <= trade.sell_entry * (1 - trade.tp_pct):
        return "TP_HIT"
    if hhmm >= eod_hhmm:
        return "EOD"
    return ""


def close_trade(trade: Trade, sell_px: float, buy_px: float, ts: datetime, reason: str):
    sell_fill = sell_px + (SLIPPAGE_TICKS * TICK + sell_px * SLIPPAGE_PCT)  # buy back
    buy_fill = max(0.0, buy_px - (SLIPPAGE_TICKS * TICK + buy_px * SLIPPAGE_PCT))
    trade.exit_ts = ts
    trade.exit_reason = reason
    trade.sell_exit = round(sell_fill, 2)
    trade.buy_exit = round(buy_fill, 2)

    gross = (
        (trade.sell_entry - trade.sell_exit) + (trade.buy_exit - trade.buy_entry)
    ) * trade.qty
    turnover = (
        trade.sell_entry + trade.sell_exit + trade.buy_entry + trade.buy_exit
    ) * trade.qty
    trade.costs = round(4 * BROKERAGE_PER_ORDER + turnover * STAT_CHARGES_PCT, 2)
    trade.pnl = round(gross - trade.costs, 2)


MARGIN_FLOOR_PER_LOT = 30_000.0  # NSE hedged-spread margin reality (SPAN+exposure
                                 # after spread benefit) — max-loss alone understates it


def margin_per_lot(wing: int, net_credit: float) -> float:
    """Defined-risk spread: exchange margin ≈ max(max loss + buffer, NSE floor)."""
    return max((wing - net_credit) * LOT_SIZE * 1.15, MARGIN_FLOOR_PER_LOT)


def max_lots(capital: float, wing: int, net_credit: float) -> int:
    m = margin_per_lot(wing, net_credit)
    return max(0, int((capital * 0.95) // m)) if m > 0 else 0
