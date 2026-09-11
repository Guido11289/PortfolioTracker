"""Eenmalig: wist ALLE sector/instrument-type-data (StockMetadata,
StockSectorWeight, StockInstrumentType) zodat de volgende
"Sync sector-data"-run alles opnieuw ophaalt met de identiteitscheck-fix
in data/sector_provider.py (_verified_ticker). Nodig omdat de huidige
data mogelijk vervuild is door de Yahoo/yfinance-tickerverwisseling die we
zagen (zie diagnose_sector_data.py-output: Vanguard S&P 500 en iShares AEX
hadden identieke sectorwegingen).

Draai:
    python -m my_portfolio.scripts.reset_sector_data
Daarna in de UI op "Sync sector-data (Yahoo)" klikken (of
POST /api/personal/sync-sector-metadata?force=true).
"""
from my_portfolio.database import PersonalSessionLocal
from my_portfolio.models import StockMetadata, StockSectorWeight, StockInstrumentType

pdb = PersonalSessionLocal()
try:
    n1 = pdb.query(StockMetadata).delete()
    n2 = pdb.query(StockSectorWeight).delete()
    n3 = pdb.query(StockInstrumentType).delete()
    pdb.commit()
    print(f"Verwijderd: {n1} StockMetadata, {n2} StockSectorWeight, {n3} StockInstrumentType")
    print("Klaar. Draai nu een nieuwe sync (knop of POST .../sync-sector-metadata?force=true).")
except Exception:
    pdb.rollback()
    raise
finally:
    pdb.close()
