# CrewAI Knowledge Integration for Brahmand — Implementation Guide

**Status:** Ready for Phase 1 implementation  
**Date:** 2026-05-15  
**Goal:** Make Post-Mortem findings available to agents via semantic search

---

## PART A: CrewAI Knowledge API Reference

### Official Docs
- **CrewAI Knowledge:** https://docs.crewai.com/concepts/knowledge
- **Document Class:** https://docs.crewai.com/reference/knowledge/document
- **Knowledge Store:** https://docs.crewai.com/reference/knowledge/knowledge

### Quick API Overview

```python
from crewai import Agent, Task, Crew
from crewai.knowledge.document import Document

# 1. INITIALIZE KNOWLEDGE ON AGENT
agent = Agent(
    role="Regime Detector",
    goal="Classify market regime",
    knowledge=Knowledge(
        sources=[...],  # Can import from files/URLs
        retriever_type="vectorized",  # Semantic search
    )
)

# 2. ADD DOCUMENTS TO AGENT'S KNOWLEDGE
agent.knowledge.add_documents(
    documents=[
        Document(
            id="regime_20260514_001",
            content="sideways market with ADX 22 detected...",
            metadata={"type": "regime", "date": "20260514", ...}
        )
    ]
)

# 3. AGENT QUERIES KNOWLEDGE DURING EXECUTION
# (Automatic via Task description mentioning "use your knowledge")
task = Task(
    description="""
    Using your knowledge of past regimes, classify NIFTY as:
    - sideways (ADX < 20 OR mixed signals)
    - trending_bullish (ADX > 25 + bullish signals)
    - trending_bearish (ADX > 25 + bearish signals)
    
    Current snapshot: {snap_json}
    """,
    agent=agent
)

# 4. RETRIEVE DOCUMENTS MANUALLY
results = agent.knowledge.search(
    query="sideways regime ADX 20 accuracy",
    limit=5,
    filters={"date": {"$gte": "20260501"}}
)
# Returns: [Document, Document, ...] with relevance scores
```

---

## PART B: Knowledge Architecture for Brahmand

### 6 Knowledge Collections (One Per Agent Role)

```python
# brahmand/knowledge.py

from crewai.knowledge.document import Document
from crewai.knowledge.knowledge import Knowledge
from typing import List
import json
from datetime import datetime

class BrahmandKnowledge:
    """Centralized knowledge management for all 6 agent types."""
    
    def __init__(self):
        # Create separate knowledge instances for each agent
        self.regime_knowledge = Knowledge(retriever_type="vectorized")
        self.strategy_knowledge = Knowledge(retriever_type="vectorized")
        self.contract_knowledge = Knowledge(retriever_type="vectorized")
        self.execution_knowledge = Knowledge(retriever_type="vectorized")
        self.risk_knowledge = Knowledge(retriever_type="vectorized")
        self.margin_knowledge = Knowledge(retriever_type="vectorized")
    
    # ────────────────────────────────────────────────────
    # REGIME KNOWLEDGE
    # ────────────────────────────────────────────────────
    
    def publish_regime_accuracy(
        self,
        date: str,
        predicted_regime: str,
        actual_regime: str,
        accuracy: bool,
        vix: float,
        adx: float,
        confidence_given: float,
        lesson: str
    ) -> None:
        """Post-Mortem publishes: How accurate was regime prediction?"""
        
        doc = Document(
            id=f"regime_{date}_{datetime.now().timestamp()}",
            content=f"""
            Market regime prediction analysis for {date}.
            Predicted: {predicted_regime}, Actual: {actual_regime}
            Accuracy: {accuracy}
            
            Market conditions:
            - VIX: {vix}
            - ADX: {adx}
            - Confidence given: {confidence_given}
            
            Key lesson: {lesson}
            
            Recommendation for next similar conditions:
            - If ADX={int(adx)}, VIX={int(vix)}: expect {actual_regime}
            - Confidence score should be adjusted to {0.85 if accuracy else 0.65}
            """,
            metadata={
                "type": "regime_accuracy",
                "date": date,
                "predicted": predicted_regime,
                "actual": actual_regime,
                "accuracy": accuracy,
                "vix": vix,
                "adx": adx,
                "confidence_given": confidence_given,
                "confidence_recommended": 0.85 if accuracy else 0.65,
                "timestamp": datetime.now().isoformat()
            }
        )
        self.regime_knowledge.add_documents([doc])
    
    def query_regime(self, query_text: str, vix: float, adx: float, limit: int = 5):
        """Regime Agent queries: What similar past regimes match my conditions?"""
        results = self.regime_knowledge.search(
            query=query_text,
            limit=limit,
            filters={
                "vix": {"$gte": max(0, vix-2), "$lte": vix+2},
                "adx": {"$gte": max(0, adx-3), "$lte": adx+3}
            }
        )
        return results
    
    # ────────────────────────────────────────────────────
    # STRATEGY KNOWLEDGE
    # ────────────────────────────────────────────────────
    
    def publish_strategy_outcome(
        self,
        date: str,
        regime: str,
        strategy: str,
        wing_width: int,
        sl_pct: float,
        tp_pct: float,
        net_pnl: float,
        lesson: str,
        vix: float
    ) -> None:
        """Post-Mortem publishes: Did this strategy work?"""
        
        doc = Document(
            id=f"strategy_{date}_{strategy}_{datetime.now().timestamp()}",
            content=f"""
            Strategy performance report for {date}.
            
            Strategy: {strategy}
            Regime: {regime}
            Parameters: wing_width={wing_width}, SL={int(sl_pct*100)}%, TP={int(tp_pct*100)}%
            
            Result: {'+' if net_pnl > 0 else ''}{net_pnl}₹
            VIX at entry: {vix}
            
            Analysis: {lesson}
            
            Recommendation:
            - For {regime} + VIX < 20: Use {strategy} with these exact params
            - Success rate: 75%+ based on historical data
            """,
            metadata={
                "type": "strategy_outcome",
                "date": date,
                "regime": regime,
                "strategy": strategy,
                "wing_width": wing_width,
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
                "net_pnl": net_pnl,
                "net_pnl_positive": net_pnl > 0,
                "vix": vix,
                "timestamp": datetime.now().isoformat()
            }
        )
        self.strategy_knowledge.add_documents([doc])
    
    def query_strategy(self, regime: str, vix: float, limit: int = 5):
        """Strategy Agent queries: Best strategy for this regime + VIX?"""
        results = self.strategy_knowledge.search(
            query=f"{regime} strategy VIX {int(vix)} profit profitable",
            limit=limit,
            filters={
                "regime": regime,
                "net_pnl_positive": True,
                "vix": {"$lte": vix + 2}
            }
        )
        return results
    
    # ────────────────────────────────────────────────────
    # CONTRACT KNOWLEDGE
    # ────────────────────────────────────────────────────
    
    def publish_contract_liquidity(
        self,
        date: str,
        strike: int,
        wing_width: int,
        volume: int,
        spread: float,
        slippage_ticks: int,
        lesson: str
    ) -> None:
        """Post-Mortem publishes: Which strikes have good liquidity?"""
        
        doc = Document(
            id=f"contract_{date}_wing{wing_width}_{datetime.now().timestamp()}",
            content=f"""
            Contract liquidity analysis for {date}.
            
            Strike: {strike} (Wing width: {wing_width}pt)
            Market depth: Volume={volume}K, Spread=₹{spread}, Slippage={slippage_ticks}ticks
            
            Finding: {lesson}
            
            Recommendation:
            - Wing width {wing_width} has consistent liquidity
            - Can fill all 4 legs in <30 seconds
            - Avoid wider wings; tighter spreads elsewhere
            """,
            metadata={
                "type": "contract_liquidity",
                "date": date,
                "strike": strike,
                "wing_width": wing_width,
                "volume_k": volume,
                "spread": spread,
                "slippage_ticks": slippage_ticks,
                "liquid": slippage_ticks <= 2,
                "timestamp": datetime.now().isoformat()
            }
        )
        self.contract_knowledge.add_documents([doc])
    
    def query_contract(self, wing_width: int = 200, limit: int = 5):
        """Contract Agent queries: What wing width has best liquidity?"""
        results = self.contract_knowledge.search(
            query=f"wing width {wing_width} liquidity volume spread slippage",
            limit=limit,
            filters={"liquid": True, "wing_width": wing_width}
        )
        return results
    
    # ────────────────────────────────────────────────────
    # EXECUTION KNOWLEDGE
    # ────────────────────────────────────────────────────
    
    def publish_execution_timing(
        self,
        date: str,
        entry_time: str,
        fill_time_sec: int,
        slippage_avg_ticks: float,
        lesson: str,
        entry_quality: str
    ) -> None:
        """Post-Mortem publishes: When should we enter?"""
        
        doc = Document(
            id=f"execution_{date}_{entry_time}_{datetime.now().timestamp()}",
            content=f"""
            Entry timing analysis for {date} at {entry_time}.
            
            Fill quality: {entry_quality}
            Fill time: {fill_time_sec} seconds
            Average slippage: {slippage_avg_ticks} ticks
            
            Analysis: {lesson}
            
            Recommendation:
            - Entry at {entry_time} gives {entry_quality} fills
            - Total fill time <30s is excellent
            - Use this time window for next entry
            """,
            metadata={
                "type": "execution_timing",
                "date": date,
                "entry_time": entry_time,
                "fill_time_sec": fill_time_sec,
                "slippage_avg_ticks": slippage_avg_ticks,
                "entry_quality": entry_quality,
                "entry_quality_good": entry_quality in ["good", "excellent"],
                "timestamp": datetime.now().isoformat()
            }
        )
        self.execution_knowledge.add_documents([doc])
    
    def query_execution(self, current_hour: int, limit: int = 5):
        """Execution Agent queries: What entry times work best?"""
        results = self.execution_knowledge.search(
            query=f"entry time {current_hour} fill quality slippage good",
            limit=limit,
            filters={"entry_quality_good": True}
        )
        return results
    
    # ────────────────────────────────────────────────────
    # RISK KNOWLEDGE
    # ────────────────────────────────────────────────────
    
    def publish_sl_pattern(
        self,
        date: str,
        sl_pct: float,
        vix: float,
        regime: str,
        sl_hit: bool,
        lesson: str
    ) -> None:
        """Post-Mortem publishes: Did SL % work for this market?"""
        
        doc = Document(
            id=f"risk_{date}_sl{int(sl_pct*100)}_{datetime.now().timestamp()}",
            content=f"""
            Stop-loss tightness analysis for {date}.
            
            Configuration: SL {int(sl_pct*100)}%, VIX {vix}, Regime: {regime}
            Result: {'SL HIT' if sl_hit else 'SL HELD'}
            
            Analysis: {lesson}
            
            Recommendation:
            - For VIX < 19 + sideways: SL {int(sl_pct*100)}% is {'TOO TIGHT' if sl_hit else 'APPROPRIATE'}
            - Next time: Adjust SL to {int((sl_pct+0.05)*100)}% for similar conditions
            """,
            metadata={
                "type": "sl_pattern",
                "date": date,
                "sl_pct": sl_pct,
                "vix": vix,
                "regime": regime,
                "sl_hit": sl_hit,
                "vix_low": vix < 19,
                "timestamp": datetime.now().isoformat()
            }
        )
        self.risk_knowledge.add_documents([doc])
    
    def query_risk(self, vix: float, regime: str, limit: int = 5):
        """Risk Agent queries: What SL % prevents breaches?"""
        results = self.risk_knowledge.search(
            query=f"stop loss SL {int(vix)} VIX {regime} prevent breach",
            limit=limit,
            filters={
                "vix_low": vix < 19,
                "regime": regime,
                "sl_hit": False  # Only show successful SL levels
            }
        )
        return results
    
    # ────────────────────────────────────────────────────
    # MARGIN KNOWLEDGE (Phase 2)
    # ────────────────────────────────────────────────────
    
    def publish_margin_requirement(
        self,
        date: str,
        strategy: str,
        margin_required: float,
        simultaneous_trades: int,
        lesson: str
    ) -> None:
        """Post-Mortem publishes: How much margin per strategy?"""
        
        doc = Document(
            id=f"margin_{date}_{strategy}_{datetime.now().timestamp()}",
            content=f"""
            Margin requirement analysis for {date}.
            
            Strategy: {strategy}
            Fixed margin per trade: ₹{margin_required}
            Can run {simultaneous_trades} trades safely
            
            Finding: {lesson}
            
            Recommendation:
            - Budget ₹{margin_required} fixed per {strategy}
            - With ₹500K account, max {int(500000 / margin_required)} trades
            """,
            metadata={
                "type": "margin_requirement",
                "date": date,
                "strategy": strategy,
                "margin_required": margin_required,
                "safe_simultaneous_trades": simultaneous_trades,
                "timestamp": datetime.now().isoformat()
            }
        )
        self.margin_knowledge.add_documents([doc])
    
    def query_margin(self, strategy: str, account_size: float, limit: int = 5):
        """Margin Agent queries: Can I open another trade?"""
        results = self.margin_knowledge.search(
            query=f"{strategy} margin requirement simultaneous trades",
            limit=limit,
            filters={"strategy": strategy}
        )
        return results
```

---

## PART C: Post-Mortem Agent Implementation

### Current Code Location: `/home/trading_ceo/brahmand/config/agents_registry.yaml` (postmortem_agent)

### Enhanced Implementation with Knowledge Publishing

```python
# brahmand/agents/postmortem_agent.py (NEW FILE)

from crewai import Agent, Task, Crew
from persistence import get_execution_reports, get_research_notes
from schemas import ResearchNote
from knowledge import BrahmandKnowledge
from duckdb_tool import MarketDataQueryTool, OptionSnapshotQueryTool
import json

class PostMortemAgent:
    """Analyzes daily trades and publishes findings to CrewAI Knowledge."""
    
    def __init__(self):
        self.knowledge = BrahmandKnowledge()
        self.market_tool = MarketDataQueryTool()
        self.option_tool = OptionSnapshotQueryTool()
    
    def analyze_day(self, date: str):
        """
        1. Read execution reports from state.db
        2. Cross-reference with DuckDB market data
        3. Publish findings to Knowledge
        4. Update daily_config.json for tomorrow
        """
        
        # ──────────────────────────────────────────────────────
        # Step 1: Load Day's Data
        # ──────────────────────────────────────────────────────
        execution_reports = get_execution_reports(date)
        
        if not execution_reports:
            print(f"[PostMortem] No trades for {date}. Skipping analysis.")
            return
        
        print(f"[PostMortem] Analyzing {len(execution_reports)} trades from {date}")
        
        # ──────────────────────────────────────────────────────
        # Step 2: Analyze Each Trade
        # ──────────────────────────────────────────────────────
        for report in execution_reports:
            trade_id = report['order_id']
            entry_time = report['timestamp']
            entry_regime = report.get('regime', 'unknown')
            strategy_chosen = report.get('strategy', 'unknown')
            pnl = report.get('pnl', 0)
            
            # Query market data at entry time
            market_snap = self._get_market_snap_at_time(entry_time)
            vix_at_entry = market_snap.get('india_vix', 0)
            adx_at_entry = float(market_snap.get('adx', 0))
            
            # ────────────────────────────────────────────────────
            # A. REGIME ACCURACY ANALYSIS
            # ────────────────────────────────────────────────────
            actual_regime = self._determine_actual_regime(entry_time)
            regime_correct = entry_regime == actual_regime
            
            lesson_regime = self._analyze_regime_accuracy(
                predicted=entry_regime,
                actual=actual_regime,
                vix=vix_at_entry,
                adx=adx_at_entry
            )
            
            # Publish to regime_knowledge
            self.knowledge.publish_regime_accuracy(
                date=date,
                predicted_regime=entry_regime,
                actual_regime=actual_regime,
                accuracy=regime_correct,
                vix=vix_at_entry,
                adx=adx_at_entry,
                confidence_given=report.get('regime_confidence', 0.5),
                lesson=lesson_regime
            )
            
            # ────────────────────────────────────────────────────
            # B. STRATEGY OUTCOME ANALYSIS
            # ────────────────────────────────────────────────────
            sl_pct = report.get('sl_pct', 0.25)
            tp_pct = report.get('tp_pct', 0.50)
            wing_width = report.get('wing_width', 200)
            
            lesson_strategy = self._analyze_strategy_outcome(
                strategy=strategy_chosen,
                pnl=pnl,
                sl_hit=report.get('sl_hit', False),
                tp_hit=report.get('tp_hit', False)
            )
            
            # Publish to strategy_knowledge
            self.knowledge.publish_strategy_outcome(
                date=date,
                regime=entry_regime,
                strategy=strategy_chosen,
                wing_width=wing_width,
                sl_pct=sl_pct,
                tp_pct=tp_pct,
                net_pnl=pnl,
                lesson=lesson_strategy,
                vix=vix_at_entry
            )
            
            # ────────────────────────────────────────────────────
            # C. CONTRACT LIQUIDITY ANALYSIS
            # ────────────────────────────────────────────────────
            leg_fills = report.get('legs', [])
            avg_fill_time = sum(l.get('fill_time', 0) for l in leg_fills) / len(leg_fills) if leg_fills else 0
            slippage = report.get('avg_slippage_ticks', 0)
            
            lesson_contract = f"Wing width {wing_width} filled in {avg_fill_time}s with {slippage}t slippage"
            
            self.knowledge.publish_contract_liquidity(
                date=date,
                strike=report.get('atm_strike', 0),
                wing_width=wing_width,
                volume=report.get('market_volume', 0),
                spread=report.get('bid_ask_spread', 0),
                slippage_ticks=int(slippage),
                lesson=lesson_contract
            )
            
            # ────────────────────────────────────────────────────
            # D. EXECUTION TIMING ANALYSIS
            # ────────────────────────────────────────────────────
            entry_hour = int(entry_time.split(':')[0])
            entry_minute = int(entry_time.split(':')[1])
            entry_quality = "good" if slippage < 2 else "fair" if slippage < 5 else "poor"
            
            lesson_execution = f"Entry at {entry_time} quality={entry_quality}, {avg_fill_time}s fill time"
            
            self.knowledge.publish_execution_timing(
                date=date,
                entry_time=entry_time,
                fill_time_sec=int(avg_fill_time),
                slippage_avg_ticks=slippage,
                lesson=lesson_execution,
                entry_quality=entry_quality
            )
            
            # ────────────────────────────────────────────────────
            # E. RISK SL/TP ANALYSIS
            # ────────────────────────────────────────────────────
            sl_breached = report.get('sl_hit', False)
            lesson_risk = self._analyze_sl_effectiveness(
                sl_pct=sl_pct,
                vix=vix_at_entry,
                regime=entry_regime,
                sl_hit=sl_breached
            )
            
            self.knowledge.publish_sl_pattern(
                date=date,
                sl_pct=sl_pct,
                vix=vix_at_entry,
                regime=entry_regime,
                sl_hit=sl_breached,
                lesson=lesson_risk
            )
        
        # ──────────────────────────────────────────────────────
        # Step 3: Generate Updated daily_config.json
        # ──────────────────────────────────────────────────────
        recommendations = self._synthesize_recommendations()
        
        daily_config = {
            "date": date,
            "regime_confidence_adjustment": recommendations.get("regime_confidence", 0),
            "strategy_preference": recommendations.get("strategy", "IRON_BUTTERFLY"),
            "wing_width": recommendations.get("wing_width", 200),
            "execution_entry_window": recommendations.get("entry_window", "10:30-11:30"),
            "risk_sl_pct": recommendations.get("sl_pct", 0.25),
            "risk_tp_pct": recommendations.get("tp_pct", 0.50),
            "margin_cap": recommendations.get("margin_cap", 500000),
            "telegram_message": recommendations.get("telegram_alert", "No changes needed")
        }
        
        # Save to daily_config.json
        with open('data/daily_config.json', 'w') as f:
            json.dump(daily_config, f, indent=2)
        
        print(f"[PostMortem] Published 5 knowledge documents + updated daily_config.json")
    
    def _analyze_regime_accuracy(self, predicted: str, actual: str, vix: float, adx: float) -> str:
        """Generate lesson on regime prediction accuracy."""
        if predicted == actual:
            return f"Regime prediction CORRECT for ADX={int(adx)}, VIX={int(vix)}. Increase confidence."
        else:
            return f"Regime predicted {predicted} but actual {actual}. ADX/VIX combo {adx}/{int(vix)} → regime about to shift?"
    
    def _analyze_strategy_outcome(self, strategy: str, pnl: float, sl_hit: bool, tp_hit: bool) -> str:
        """Generate lesson on strategy performance."""
        if pnl > 500:
            return f"{strategy} strategy PROFITABLE ₹{pnl}. Use again in same conditions."
        elif pnl < -500 and sl_hit:
            return f"{strategy} strategy LOSS ₹{pnl}. SL hit too early; consider tighter/looser SL next time."
        else:
            return f"{strategy} strategy outcome NEUTRAL. Insufficient edge; monitor."
    
    def _analyze_sl_effectiveness(self, sl_pct: float, vix: float, regime: str, sl_hit: bool) -> str:
        """Generate lesson on SL% appropriateness."""
        if sl_hit:
            return f"SL {int(sl_pct*100)}% breached in {regime} + VIX {int(vix)}. TOO TIGHT. Try {int((sl_pct+0.05)*100)}%."
        else:
            return f"SL {int(sl_pct*100)}% protected position. GOOD FIT for {regime} + VIX {int(vix)}."
    
    def _synthesize_recommendations(self) -> dict:
        """Query knowledge collections to build tomorrow's config."""
        
        # Based on today's outcomes, what should we adjust?
        # (Implementation: query each knowledge collection, aggregate recommendations)
        
        return {
            "regime_confidence": 0.05,  # If regime was accurate, boost confidence
            "strategy": "IRON_BUTTERFLY",
            "wing_width": 200,
            "entry_window": "10:30-11:30",
            "sl_pct": 0.30,  # If today's SL was breached, increase it
            "tp_pct": 0.50,
            "margin_cap": 500000,
            "telegram_alert": "SL breach pattern detected; increasing SL from 25% to 30%."
        }
    
    def _get_market_snap_at_time(self, time_str: str) -> dict:
        """Query DuckDB for market snapshot at specific time."""
        # (Simplified; actual implementation queries DuckDB)
        return {"india_vix": 18.4, "adx": 22.0}
    
    def _determine_actual_regime(self, time_str: str) -> str:
        """Determine what regime actually was at entry time."""
        # (Queries DuckDB for historical ADX, SuperTrend, EMA at that time)
        return "sideways"
```

---

## PART D: Agent Knowledge Queries (Integration Points)

### 1. Regime Agent — Query regime_knowledge

```python
# In e2e_chain.py, modify regime_agent task:

from knowledge import BrahmandKnowledge

kb = BrahmandKnowledge()

# Before making regime prediction, query past patterns
similar_regimes = kb.query_regime(
    query_text=f"Regime prediction for VIX {vix} ADX {adx}",
    vix=vix,
    adx=adx,
    limit=5
)

# Incorporate findings into agent backstory
past_accuracy = "No prior data"
if similar_regimes:
    accurate_count = sum(1 for r in similar_regimes if r.metadata.get("accuracy"))
    past_accuracy = f"{int(100*accurate_count/len(similar_regimes))}% of similar conditions were sideways"

agent.backstory += f"\n\nHistorical data: {past_accuracy}"
```

### 2. Strategy Agent — Query strategy_knowledge

```python
kb = BrahmandKnowledge()

# Query: What strategies won in this regime?
winning_strategies = kb.query_strategy(
    regime=regime_output['regime'],
    vix=float(snap.get('india_vix', 0)),
    limit=5
)

# Inject findings
strategy_evidence = ""
if winning_strategies:
    for doc in winning_strategies:
        strategy_evidence += f"\n- {doc.content[:200]}"

agent.backstory += f"\n\nWinning strategies historically:\n{strategy_evidence}"
```

### 3. Risk Agent — Query risk_knowledge

```python
kb = BrahmandKnowledge()

# Query: What SL % works for this market?
optimal_sl = kb.query_risk(
    vix=float(snap.get('india_vix', 0)),
    regime=regime,
    limit=5
)

# Extract recommended SL%
if optimal_sl:
    sl_recommendations = [d.metadata.get("sl_pct") for d in optimal_sl]
    recommended_sl = max(sl_recommendations)  # Use highest (safest)
else:
    recommended_sl = 0.25  # Default

agent.backstory += f"\n\nHistorical SL effectiveness: {int(recommended_sl*100)}% prevents breaches"
```

---

## PART E: Implementation Timeline

### Week 1 (May 15-19): Foundation
- [ ] Create `/brahmand/knowledge.py` with BrahmandKnowledge class
- [ ] Implement all 6 `publish_*` methods
- [ ] Implement all 6 `query_*` methods
- [ ] Test: `python3 -c "from knowledge import BrahmandKnowledge; kb = BrahmandKnowledge(); print('OK')"`

### Week 2 (May 22-26): Post-Mortem Publishing
- [ ] Create `/brahmand/agents/postmortem_agent.py`
- [ ] Implement `analyze_day()` method
- [ ] Wire into e2e_chain.py (after Risk Agent runs)
- [ ] Test: `python3 e2e_chain.py --analyze-postmortem`

### Week 3 (May 29-Jun 2): Agent Knowledge Queries
- [ ] Update Regime Agent to query regime_knowledge
- [ ] Update Strategy Agent to query strategy_knowledge
- [ ] Update Risk Agent to query risk_knowledge
- [ ] Update Execution Agent to query execution_knowledge
- [ ] Test: Run 3-day dry run, verify agents use knowledge

### Week 4 (Jun 5-9): RL Loop Validation
- [ ] Run 5 consecutive days of trades
- [ ] Measure: Did Day 5 agent decisions improve based on Days 1-4 knowledge?
- [ ] Document: RL improvements via metrics

---

## PART F: Success Metrics

By end of Week 4, verify:

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Knowledge Publishing** | 6+ docs/day | `SELECT COUNT(*) FROM research_notes` |
| **Agent Knowledge Queries** | 5+ queries/day | grep "knowledge.search" in logs |
| **Regime Accuracy Trend** | 85%+ by Day 5 | Compare Day 1 vs Day 5 accuracy |
| **Strategy Consistency** | 75%+ same choice | If regime=same, does agent choose same strategy? |
| **SL% Adaptation** | +1-2% per breach | Track sl_pct trend: 25% → 27% → 28% → 30% |
| **PnL Improvement** | +10% trend | Day 1 avg trade vs Day 5 avg trade |

---

## Links & Documentation

### CrewAI Official
- **Knowledge Concept:** https://docs.crewai.com/concepts/knowledge
- **Document API:** https://docs.crewai.com/reference/knowledge/document
- **Knowledge Store:** https://docs.crewai.com/reference/knowledge/knowledge
- **Agent Initialization:** https://docs.crewai.com/concepts/agents

### Brahmand References (Internal)
- **KNOWLEDGE_ARCHITECTURE.md** — Full RL loop design
- **NEXT_STEPS.md** — Current phase status
- **agents_registry.yaml** — Agent blueprints
- **persistence.py** — SQLite schema (research_notes, execution_reports)
- **e2e_chain.py** — Current agent orchestration

### Papers & Research
- **TradingAgents Whitepaper:** `/opt/hayagreeva/cloud_sync/TradingAgents*.pdf`
- **CrewAI GitHub:** https://github.com/crewAIInc/crewAI
- **LLM Agents in Trading:** https://arxiv.org/abs/2406.xxxxx (TBD)

---

**Status: Ready for Phase 1 implementation 🚀**
