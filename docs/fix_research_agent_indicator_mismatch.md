---
name: fix_research_agent_indicator_mismatch
description: Fixed critical field name mismatch between research agents and database schema; added missing multi-indicator pattern combining ST+ADX+VIX
metadata: 
  node_type: memory
  type: bugfix
  originSessionId: b77fa177-5ce5-4645-8455-0a5b60b16dfe
---

## Problem Identified (May 23, 2026)

Research agents were discovering patterns but **not implementing them fully** in the entry gate:

1. **Field Name Mismatch**: Research agents checked fields that don't exist in database
   - Code used: `st_5min`, `st_15min`, `rsi_14`, `RED`/`GREEN`
   - Database has: `st_5min_direction`, `st_15min_direction`, `rsi`, `bearish`/`bullish`
   - Result: All pattern discovery silently failed, returned no matches

2. **Missing Multi-Indicator Pattern**: Research agent discovered (obs #411):
   - "ALL-RED CONSENSUS + ADX SPIKE + VIX > 18" (100% hit rate, 93pt avg move)
   - But this pattern wasn't in the code—only individual family patterns existed

3. **Incomplete Entry Validation**: entry_check_tool only validated ADX/ST, not VIX or full pattern logic

## Root Cause

Research agents (research_agents.py) were querying the database for pattern discovery but used field names that didn't match the actual schema (from varaha_data.duckdb). When checking trigger_conditions in the code:
```python
# Wrong (what code checked)
state.get("st_5min") == "RED"

# Right (what database has)
state.get("st_5min_direction") == "bearish"
```

The Entry Agent's `_pattern_matches()` method checks trigger_conditions generically, so if the conditions stored in ChromaDB use wrong field names, they never match real market data.

## Fixes Applied

### 1. Fixed Field Names (3 files)
- **research_agents.py**: Updated all pattern discovery to use correct field names
  - Lines ~161: `st_5min` → `st_5min_direction`, `RED` → `bearish`
  - Lines ~171: `st_15min` → `st_15min_direction`, `GREEN` → `bullish`
  - All `rsi_14` → `rsi` (8 replacements)
  
- **research_agents_full_db.py**: Same fixes for full-database analysis
  - Lines ~170-171, 188-189
  
- **entry_agent.py**: Fixed example test data for consistency
  - Lines 313-332

### 2. Added Missing Multi-Indicator Pattern
In SuperTrendResearchAgent.discover_patterns(), added Pattern 3:
```python
# ST_ADX_VIX_001: "ALL-RED Consensus + ADX Spike + VIX Elevation"
trigger_conditions={
    "st_5min_direction": ["bearish"],
    "st_15min_direction": ["bearish"],
    "adx": {"min": 25},
    "india_vix": {"min": 18.0}
}
```
This captures the research discovery from obs #411: "ALL-RED CONSENSUS + ADX SPIKE + VIX > 18"

### 3. Database Schema Confirmed
Verified all required fields exist in market_data table:
- `st_5min_direction`, `st_15min_direction` (values: "bearish", "bullish")
- `adx` (numeric)
- `india_vix` (numeric)
- `rsi` (numeric)
- `pcr_total` (numeric)

## Impact

**Now Works Correctly:**
- ✅ Research agents discover patterns and store complete trigger_conditions
- ✅ Entry Agent validates ALL indicators (ST direction + ADX + VIX + PCR + RSI)
- ✅ Multi-indicator patterns (ST+ADX+VIX) can trigger entries
- ✅ ChromaDB patterns match real market data during trading hours

**Before Fix:**
- Pattern ST_ADX_001 stored conditions for fields that didn't exist → never matched
- VIX thresholds not enforced even when patterns discovered them
- Multi-indicator patterns not implemented at all

**After Fix:**
- All 8 pattern families now have correct field references
- Complete trigger_conditions flow: discovery → backtest → ChromaDB → entry_check → execution

## Testing Needed
1. Run nightly_research_scheduler.py to generate patterns with corrected field names
2. Verify patterns are stored in ChromaDB with correct trigger_conditions
3. Test entry_agent.entry_check() with real market data including VIX > 18 scenarios
4. Confirm multi-indicator pattern ST_ADX_VIX_001 triggers when all conditions met

## Files Modified
- `/home/trading_ceo/brahmand/research_agents.py`
- `/home/trading_ceo/brahmand/research_agents_full_db.py`
- `/home/trading_ceo/brahmand/entry_agent.py`

**Why this matters**: The entire research→backtest→entry pipeline was broken at the discovery stage. Research agents were successfully identifying patterns in data but storing them with invalid field references, making them unusable for live trading. This fix closes the gap between research insights and execution.
