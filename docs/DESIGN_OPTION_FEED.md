# Option Feed WebSocket — Design Document

Status: DRAFT v3 · Review with Claude before implementation

## Problem

position_manager's 1-min monitor never detected SL/TP hits today:
- The LLM (risk_agent_crew) sees static entry data, never calls monitor_pnl_greeks
- monitor_pnl_greeks queries DuckDB option_snapshots → lock contention risk
- The enricher fetches option chain via 22 REST calls/min — should be WebSocket
- Current data capture pipeline has no per-strike option LTPs at all
- P&L sat at 0.0 from 09:16 to 15:31 — zero active monitoring

## Solution

Extend the **Penguin data capture pipeline** with a rolling ATM ±5 option WebSocket feed.
Existing `feed.py` handles index OHLCV. A new sibling process subscribes to option
tokens, rebalances on every ATM shift of ±50, and writes LTPs to Redis. The
consumer persists to SQLite. position_manager reads deterministically.

## Architecture (Penguin Pipeline)

```
┌──────────────────────────────────────────────────────────────────────┐
│  WebSocket Layer (systemd)                                           │
│                                                                      │
│  feed.service (existing)                                             │
│  ├── Shoonya WS → NIFTY index token                                  │
│  └── LPUSH feed:NIFTY  (OHLCV bars)                                  │
│                                                                      │
│  option-feed.service (NEW)                                           │
│  ├── Reads spot from REDIS feed:NIFTY  (for ATM calculation)        │
│  ├── Shoonya WS → 22 option tokens (ATM ±5 strikes × CE/PE)         │
│  ├── Rebalances on every ATM shift of ±50                           │
│  └── LPUSH feed:NIFTY:options  (per-tick LTPs)                      │
│                                                                      │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ Redis
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Consumer Layer (systemd)                                            │
│                                                                      │
│  consumer-nifty.service (EDIT)                                       │
│  ├── Already reads feed:NIFTY                                        │
│  ├── ADD: Also reads feed:NIFTY:options                              │
│  └── Writes to SQLite:                                              │
│      - market_data  (existing, OHLCV)                                │
│      - option_prices (NEW, per-tick LTPs)                           │
│                                                                      │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ SQLite (WAL mode)
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Consumer Applications                                               │
│                                                                      │
│  enricher-nifty.service (EDIT)                                       │
│  ├── OLD: 22 REST calls get_option_chain()                           │
│  └── NEW: SELECT * FROM option_prices ORDER BY timestamp DESC LIMIT 22│
│                                                                      │
│  position_manager.run_bridge() (EDIT)                                │
│  ├── _check_sl_tp(trade) ← DETERMINISTIC, reads option_prices        │
│  └── risk_agent_crew.evaluate_trade() ← LLM (morph/shift only)      │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## ATM Rebalance (option-feed.py)

### WebSocket Subscribe/Unsubscribe — Verified

Both `subscribe()` and `unsubscribe()` are **official Shoonya WebSocket API methods**
(confirmed via https://github.com/Shoonya-Dev/ShoonyaApi-py#md-subscribe).
Subscribe is already used in feed.py at start. Unsubscribe works mid-flight via
the same WebSocket — just send `{"t": "u"/"ud", "k": "NSE|token"}`.

**Current NorenApiPy issue:** `unsubscribe()` is commented out (NorenApi.py:562).
Fix: uncomment the method before deployment. It's a simple `__ws_send()` call.

### Rolling Window Logic

```
Initial state: ATM = 25000
  Subscribed strikes: 24750, 24800, 24850, 24900, 24950,
                       25000, 25050, 25100, 25150, 25200, 25250
  (11 strikes × CE + PE = 22 tokens)

Spot rises → new ATM = 25050 (shift of +50)
  UNSUBSCRIBE: 24750 CE, 24750 PE    ← 2 WebSocket messages
  SUBSCRIBE:   25300 CE, 25300 PE     ← 2 WebSocket messages  
  Window now:  24800–25300 (±5 from new ATM 25050)

Spot rises again → new ATM = 25100 (another +50)
  UNSUBSCRIBE: 24800 CE, 24800 PE
  SUBSCRIBE:   25350 CE, 25350 PE
  Window now:  24850–25350
```

Each rebalance: 4 WebSocket messages (2 unsub + 2 sub), < 100ms.

```python
def rebalance_subscriptions(api, old_atm: int, new_atm: int, expiry: str):
    """When ATM shifts by ±50, drop furthest old strikes, add new ones."""
    if abs(new_atm - old_atm) < 50:
        return

    old_window = [old_atm + i * 50 for i in range(-5, 6)]
    new_window = [new_atm + i * 50 for i in range(-5, 6)]

    to_unsub = set(old_window) - set(new_window)
    to_sub   = set(new_window) - set(old_window)

    for strike in to_unsub:
        for ot in ("CE", "PE"):
            tsym = f"NIFTY{expiry}{strike}{ot}"
            api.unsubscribe(f"NSE|{tsym}")

    for strike in to_sub:
        for ot in ("CE", "PE"):
            tsym = f"NIFTY{expiry}{strike}{ot}"
            api.subscribe(f"NSE|{tsym}")

    # Tell consumer to purge stale rows
    r.set("feed:NIFTY:options:window", json.dumps(new_window))
```

## option_feed.py — Tick Processing

```python
def on_tick(msg):
    token = msg.get("tk", "")
    ltp = float(msg.get("lp", 0))
    ts = datetime.now(IST).isoformat()
    tsym = token_map.get(token)  # Shoonya token → NIFTY02JUN26C25000

    if not tsym:
        return

    option_type = "CE" if tsym.endswith("CE") else "PE"
    strike = int(re.search(r"(\d{5})(CE|PE)", tsym).group(1))

    # Publish to Redis
    r.lpush("feed:NIFTY:options", json.dumps({
        "tsym": tsym,
        "strike": strike,
        "option_type": option_type,
        "ltp": ltp,
        "timestamp": ts,
    }))
    r.ltrim("feed:NIFTY:options", 0, 500_000)  # ~7 days
```

## SQLite Schema (consumer writes this)

```sql
CREATE TABLE IF NOT EXISTS option_prices (
    tsym        TEXT PRIMARY KEY,
    strike      INTEGER NOT NULL,
    option_type TEXT NOT NULL CHECK (option_type IN ('CE', 'PE')),
    ltp         REAL,
    timestamp   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_option_prices_strike
    ON option_prices(strike, option_type);
```

## Consumer Changes (instrument_consumer.py)

Existing consumer reads `feed:NIFTY` → writes `market_data`.
Add a second loop that reads `feed:NIFTY:options` → writes `option_prices`:

```python
# After existing bar processing loop:
for raw in option_ticks:
    tick = json.loads(raw)
    conn.execute(
        """INSERT OR REPLACE INTO option_prices
           (tsym, strike, option_type, ltp, timestamp)
           VALUES (?, ?, ?, ?, ?)""",
        (tick["tsym"], tick["strike"], tick["option_type"],
         tick["ltp"], tick["timestamp"]),
    )
# Purge stale strikes based on window signal
window_json = r.get("feed:NIFTY:options:window")
if window_json:
    window = json.loads(window_json)
    placeholders = ",".join("?" * len(window))
    conn.execute(
        f"DELETE FROM option_prices WHERE strike NOT IN ({placeholders})",
        window,
    )
conn.commit()
```

## Enricher Changes (instrument_enricher.py)

```python
# OLD: 22 REST calls
option_data = self.broker.get_option_chain(
    "NFO", self._get_weekly_expiry_short(), atm_strike
)

# NEW: Read from SQLite
rows = self.conn.execute(
    "SELECT strike, option_type, oi, iv, ltp FROM option_prices "
    "ORDER BY timestamp DESC LIMIT 44"  # 22 tokens × 2 rows for safety
).fetchall()
option_data = [dict(row) for row in rows]
```

Broker session still used for VIX + futures LTP (2 REST calls, not 22).

## position_manager Changes

```python
def _check_sl_tp(trade):
    """DETERMINISTIC. Runs BEFORE LLM dispatch. Reads option_prices from SQLite."""
    conn = open_state_db()
    mtm = 0.0
    for leg in trade["legs"]:
        row = conn.execute(
            "SELECT ltp FROM option_prices WHERE tsym = ?", (leg["tsym"],)
        ).fetchone()
        current_ltp = row["ltp"] if row else leg["fill_price"]

        sign = +1 if leg["action"] == "SELL" else -1
        mtm += (leg["fill_price"] - current_ltp) * 65 * sign

        if leg["action"] == "SELL":
            if current_ltp >= leg["sl"]:
                return {"action": "SL_HIT", "leg": leg, "ltp": current_ltp, "mtm": mtm}
            if current_ltp <= leg["tp"]:
                return {"action": "TP_HIT", "leg": leg, "ltp": current_ltp, "mtm": mtm}

    return {"action": "ACTIVE", "mtm": mtm}
```

## Expiry Rollover (Wednesday 15:30 or when expiry changes)

```python
def refresh_expiry():
    new_expiry = compute_weekly_expiry_date()  # existing function
    new_expiry_short = new_expiry.strftime("%d%b%Y").upper()  # "02JUN2026"
    # Rebuild full subscription list with new expiry tsyms
    rebuild_window(api, atm, new_expiry_short)
```

Triggered by: consumer detecting `expiry` change in `market_data_enriched`, or a cron at 09:14 after Wednesday EOD rollover.

## Files Changed

| File | Action | Purpose |
|------|--------|---------|
| `antariksh/option_feed.py` | NEW | WebSocket → Redis for option tick data |
| `antariksh/config/sqlite_schema.py` | EDIT | Add `option_prices` table + index |
| `/etc/systemd/system/option-feed.service` | NEW | Market-hours systemd service |
| `/etc/systemd/system/option-feed.timer` | NEW | 09:14–15:30 Mon–Fri |
| `antariksh/consumers/instrument_consumer.py` | EDIT | Also consume `feed:NIFTY:options` |
| `antariksh/enrichers/instrument_enricher.py` | EDIT | Replace REST calls with SQLite read |
| `brahmand/position_manager.py` | EDIT | Add `_check_sl_tp()` before LLM dispatch |

## Pre-Deployment Verification

- [x] **subscribe mid-flight:** ✅ Confirmed — Shoonya official docs + already used in feed.py `open_callback`
- [x] **unsubscribe mid-flight:** ✅ Confirmed — Shoonya official docs. NorenApiPy method is commented out; uncomment before deploy.
- [x] **22 tokens on single WS connection:** ✅ feed.py already handles 3 instruments. 22 option tokens is less than MCX contract load.
- [ ] **Test rebalance:** Write a test script that subscribes, then unsubscribes 2 tokens mid-flight, verifies no data loss

## What Changes vs Today

| Today | After |
|-------|-------|
| feed.py subscribes NIFTY index only | + option-feed subscribes ATM ±5 option tokens |
| No option LTPs in SQLite | option_prices table, WAL, zero lock contention |
| Enricher: 22 REST calls/min | Enricher: 2 REST calls/min (VIX + futures only) |
| position_manager: LLM "checks" SL/TP | position_manager: deterministic `_check_sl_tp()` first |
| Static ATM, no option data | Rolling ATM window, auto-rebalance ±50 shift |

## Key Decisions

1. **Separate from feed.py:** feed.py is index OHLCV with bucketing. Option feed is raw ticks, different subscribe/unsubscribe lifecycle.
2. **Redis as intermediary:** Consumer pattern already proven. Same pattern for option ticks.
3. **SQLite as sink (not Redis):** Survives restarts, WAL = zero contention, shared across consumers.
4. **Deterministic before LLM:** SL/TP are arithmetic. LLM decides morph/shift only.
5. **Expiry auto-rollover:** Consumer detects expiry change from enriched data, signals option-feed to rebuild subscriptions.
