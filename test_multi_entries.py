import sys
sys.path.insert(0, '.')
import pandas as pd
from data.mt5_loader import MT5DataLoader
from strategy.entry_engine import EntryEngine

loader = MT5DataLoader("XAUUSDm")
dfs = loader.fetch_all_timeframes()
engine = EntryEngine(dfs, symbol="XAUUSDm")
signals = engine.scan_all_models()

print(f"Total Signals / Entries Generated: {len(signals)}")
for s in signals:
    p = s.primary_plan
    print(f"\n[#{s.priority_rank}] Model: {s.model_type.value}")
    print(f"     Direction: {s.direction.value} | Confidence: {s.confidence}")
    print(f"     Storyline: {s.storyline_desc}")
    print(f"     Cascade: FTFL({s.ftfl_tf}) -> STFL({s.stfl_tf}) -> TTFL({s.ttfl_tf})")
    print(f"     Entry: {p.buffered_entry:.3f} | SL: {p.stop_loss:.3f} | TP: {p.take_profit:.3f}")
    print(f"     Distance: {s.distance_to_entry:.2f} pts | Sizing: {p.lot_size} Lots (${p.risk_amount_usd})")
    print(f"     Rationale: {s.rationale}")
