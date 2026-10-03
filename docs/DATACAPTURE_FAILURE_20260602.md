# Data Capture Failure — June 2, 2026

## Summary

| Metric | Value |
|--------|-------|
| **Last data captured** | May 29, 2026 (14:00 IST) |
| **Rows captured today (Jun 2)** | 0 |
| **NIFTY SQLite DB** | `capture_nifty.sqlite` (328 KB, last: Jun 1 23:50) |
| **SENSEX SQLite DB** | `capture_sensex.sqlite` (284 KB, last: Jun 1 23:50) |
| **Days of missing data** | May 30, Jun 1, Jun 2 |

## Root Cause

Penguin's data pipeline (feed → consumer → enricher) is managed by 7 **systemd timers**. These timers had a **`Requires=` dependency bug** that prevented them from triggering at 09:14 on market days. The services were never started.

**The pipeline chain:**
```
feed.timer (09:14)
  → feed.service — Shoonya WebSocket → Redis feed:{INST}

consumer-{nifty,sensex,mcx}.timer (09:14:30)
  → consumer-*.service — Redis → SQLite 1-min OHLCV + multi-TF

enricher-{nifty,sensex,mcx}.timer (09:15:00)
  → enricher-*.service — OHLCV → 104 enriched columns
```

None of these fired on Jun 2 (nor May 30, Jun 1).

## Fix Applied (systemd timers, not cron)

| What | When | Who |
|------|------|-----|
| `Requires=` bug fixed in 7 timer units | 2026-06-02 | Board |
| Timers re-armed | 2026-06-02 23:15 IST | Board |
| All services running and verified | 2026-06-02 23:25 IST | Confirmed |

## Current State (post-fix)

```
● feed.timer             active → triggers Wed 09:14:00
● consumer-nifty.timer   active → triggers Wed 09:14:30
● consumer-sensex.timer  active → triggers Wed 09:14:30
● consumer-mcx.timer     active → triggers Wed 09:14:30
● enricher-nifty.timer   active → triggers Wed 09:15:00
● enricher-sensex.timer  active → triggers Wed 09:15:00
● enricher-mcx.timer     active → triggers Wed 09:15:00
```

All 7 services are **enabled** and will auto-start tomorrow morning.

## Open Follow-ups

1. **`varaha_data.duckdb` bridging**: Penguin writes to `capture_*.sqlite`. But 10+ Brahmand agents read from `varaha_data.duckdb`. The EOD bridge (`tools/eod_etl.py`) copies SQLite → `research/{date}/*.duckdb` after market close, but `varaha_data.duckdb` itself is **not fed by Penguin**. Pending Board direction on whether to:
   - Run EOD ETL into `varaha_data.duckdb` (direct overwrite)
   - Repoint Brahmand agents to read `capture_*.sqlite` directly
   - Keep both paths

2. **`/etc/cron.d/antariksh-v4`**: The v4 aggregator is now **orphaned** — Penguin's consumer already produces `market_data_multitf`. Candidate for removal.

3. **No active data capture cron entries**: The crontab has no data capture entries (intentional — systemd handles it). The zombie cleanup at 06:58 and EOD cleanup at 15:35 remain.

## Verification

```bash
# Check timers are armed
systemctl list-timers 'penguin*' --all

# Check services running tomorrow
systemctl status feed.service consumer-nifty.service enricher-nifty.service

# Check SQLite growing during market
ls -la /home/trading_ceo/projects/varaha/data/capture_nifty.sqlite

# EOD warehouse bridge (after 15:40)
ls -la research/$(date +%Y-%m-%d)/nifty.duckdb
```
