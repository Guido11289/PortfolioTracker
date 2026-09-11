"""Read-only diagnose van de sector-tabellen. Wijzigt niets.

Draai:
    python -m my_portfolio.scripts.diagnose_sector_data
"""
from degiro_portfolio.database import SessionLocal, Stock
from my_portfolio.database import PersonalSessionLocal
from my_portfolio.models import StockInstrumentType, StockMetadata, StockSectorWeight

db = SessionLocal()
pdb = PersonalSessionLocal()

stocks = {s.id: s for s in db.query(Stock).all()}
types = {t.stock_id: t.quote_type for t in pdb.query(StockInstrumentType).all()}
meta = {m.stock_id: (m.sector, m.industry) for m in pdb.query(StockMetadata).all()}

weights_by_stock = {}
for w in pdb.query(StockSectorWeight).all():
    weights_by_stock.setdefault(w.stock_id, []).append((w.sector, round(w.weight, 4)))

print(f"{'stock_id':<10}{'name':<45}{'isin':<20}{'ticker':<12}{'quote_type':<15}{'sector (single)'}")
for sid, s in stocks.items():
    print(f"{sid:<10}{s.name[:43]:<45}{str(s.isin)[:18]:<20}{str(s.yahoo_ticker):<12}"
          f"{str(types.get(sid)):<15}{meta.get(sid)}")

print("\n--- StockSectorWeight (fund-sectorwegingen) per stock ---")
for sid, weights in weights_by_stock.items():
    name = stocks[sid].name if sid in stocks else "?"
    total = sum(w for _, w in weights)
    print(f"stock_id={sid} ({name}): {len(weights)} sectoren, som={total:.3f}")
    for sector, weight in sorted(weights, key=lambda x: -x[1]):
        print(f"    {sector:<30} {weight:.3f}")

db.close()
pdb.close()
