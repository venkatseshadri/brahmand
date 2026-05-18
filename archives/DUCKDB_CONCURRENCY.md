# DuckDB Lock Contention Issue

## The Problem

**DuckDB does NOT support true MRWS (Multiple Readers, Single Writer) without WAL mode.**

### What Actually Happens:

1. **Multiple readers alone** ✓ Work fine (all read-only)
   ```python
   con1 = duckdb.connect(file, read_only=True)   # ✓ Works
   con2 = duckdb.connect(file, read_only=True)   # ✓ Works
   con3 = duckdb.connect(file, read_only=True)   # ✓ Works
   ```

2. **Reader + Writer together** ✗ BLOCKS readers
   ```python
   con_write = duckdb.connect(file)              # Write mode
   con_read = duckdb.connect(file, read_only=True)  # BLOCKED!
   # ConnectionException until writer finishes
   ```

## Why Your Capture Lock Lasted 50 Minutes

From the log (2026-05-14):
- **12:15-13:05** → Varaha capture process held write lock
- **Every 5 min** → Kickoff tried to read, got `IOException: Conflicting lock`
- **After 13:10** → Capture finished, kickoff worked normally

## Solutions (in order of preference)

### 1. **Schedule Capture Outside Market Hours** (RECOMMENDED)
```bash
# Current: capture runs during 9:30-15:30 (WRONG)
# Should be: capture runs at 15:31 or 09:15 or 16:00

# Edit varaha's cron or scheduler to avoid kickoff times
```

**Why this works:** No writer = no lock contention, readers work freely.

---

### 2. **Use SQLite + WAL Mode** (if migration is possible)
SQLite supports WAL mode natively:
```python
import sqlite3
con = sqlite3.connect(file)
con.execute("PRAGMA journal_mode = WAL")
# Now readers and writers coexist!
```

But requires:
- Migrating varaha data from DuckDB → SQLite
- Updating all read/write code

---

### 3. **Separate Read-Only Copy** (complex but safe)
```
Varaha Capture → varaha_data.duckdb (write-only, isolated)
                     ↓
              [async sync every N seconds]
                     ↓
            varaha_data_replica.duckdb (read-only replica)
                     ↑
                  Kickoff reads here (always available)
```

---

### 4. **Message Queue Instead of DB** (best long-term)
```
Capture → Redis/RabbitMQ → Kickoff
# Decouples read/write, no file locking issues
```

---

## Current Mitigation

I improved retry logic in `duckdb_tool.py`:
- **Before:** 10 retries × 1s = ~10 seconds wait
- **After:** 20 retries with exponential backoff = ~71 seconds wait

This helps for **short lock holds** (< 71s) but won't help if capture runs for 50 minutes.

## Recommendation

**Stop the varaha capture process from running during 9:30-15:30.**

Once that's fixed, your kickoff should work reliably. The lock contention is 100% caused by scheduling conflict, not a code bug.
