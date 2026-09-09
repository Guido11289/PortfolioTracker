"""Tests voor analysis/sector_allocation.py.

Dit zijn precies de asserts die tot nu toe ad-hoc in de sandbox gedraaid
werden bij elke wijziging — nu blijvend, zodat een toekomstige wijziging
(bv. aan _compute_price_scales in main.py) hier automatisch op knapt i.p.v.
pas bij de volgende handmatige controle."""
from my_portfolio.analysis.sector_allocation import compute_sector_allocation
from my_portfolio.models import StockMetadata, StockSectorWeight, StockInstrumentType

from .conftest import make_stock, make_holding


def test_geen_holdings_geeft_lege_lijst(core_db, personal_db):
    assert compute_sector_allocation(core_db, personal_db) == []


def test_los_aandeel_telt_100_procent_voor_zijn_sector(core_db, personal_db):
    stock = make_stock(core_db)
    make_holding(core_db, stock, quantity=10, price=100.0, currency="EUR")
    personal_db.add(StockMetadata(stock_id=stock.id, sector="Technology", industry="Software"))
    personal_db.commit()

    result = compute_sector_allocation(core_db, personal_db)

    assert len(result) == 1
    assert result[0]["sector"] == "Technology"
    assert result[0]["value_eur"] == 1000.0
    assert result[0]["weight_pct"] == 100.0


def test_aandeel_zonder_sectordata_valt_in_unknown(core_db, personal_db):
    stock = make_stock(core_db)
    make_holding(core_db, stock, quantity=5, price=50.0, currency="EUR")
    # Bewust GEEN StockMetadata toegevoegd.

    result = compute_sector_allocation(core_db, personal_db)

    assert len(result) == 1
    assert result[0]["sector"] == "Unknown"
    assert result[0]["value_eur"] == 250.0


def test_etf_verdeelt_waarde_over_meerdere_sectoren(core_db, personal_db):
    etf = make_stock(core_db)
    make_holding(core_db, etf, quantity=10, price=100.0, currency="EUR")  # totaal 1000
    personal_db.add(StockSectorWeight(stock_id=etf.id, sector="Technology", weight=0.6))
    personal_db.add(StockSectorWeight(stock_id=etf.id, sector="Financial Services", weight=0.4))
    personal_db.commit()

    result = compute_sector_allocation(core_db, personal_db)
    by_sector = {r["sector"]: r["value_eur"] for r in result}

    assert by_sector["Technology"] == 600.0
    assert by_sector["Financial Services"] == 400.0
    assert sum(r["value_eur"] for r in result) == 1000.0


def test_gemengde_portfolio_som_klopt_met_totale_waarde(core_db, personal_db):
    """Regressietest voor het patroon dat we handmatig verifieerden in de
    sandbox: som van alle sectorwaarden == som van alle holdingwaarden,
    ongeacht de mix van losse aandelen en ETF's."""
    stock = make_stock(core_db)
    make_holding(core_db, stock, quantity=10, price=50.0, currency="EUR")  # 500
    personal_db.add(StockMetadata(stock_id=stock.id, sector="Healthcare"))

    etf = make_stock(core_db)
    make_holding(core_db, etf, quantity=20, price=25.0, currency="EUR")  # 500
    personal_db.add(StockSectorWeight(stock_id=etf.id, sector="Technology", weight=0.7))
    personal_db.add(StockSectorWeight(stock_id=etf.id, sector="Energy", weight=0.3))
    personal_db.commit()

    result = compute_sector_allocation(core_db, personal_db)

    assert sum(r["value_eur"] for r in result) == 1000.0
    assert sum(r["weight_pct"] for r in result) == 100.0


def test_scope_stocks_sluit_etfs_uit(core_db, personal_db):
    stock = make_stock(core_db)
    make_holding(core_db, stock, quantity=10, price=100.0, currency="EUR")
    personal_db.add(StockMetadata(stock_id=stock.id, sector="Healthcare"))
    personal_db.add(StockInstrumentType(stock_id=stock.id, quote_type="EQUITY"))

    etf = make_stock(core_db)
    make_holding(core_db, etf, quantity=10, price=100.0, currency="EUR")
    personal_db.add(StockInstrumentType(stock_id=etf.id, quote_type="ETF"))
    personal_db.commit()

    result = compute_sector_allocation(core_db, personal_db, scope="stocks")

    assert len(result) == 1
    assert result[0]["sector"] == "Healthcare"
    assert result[0]["value_eur"] == 1000.0


def test_scope_etfs_sluit_losse_aandelen_uit(core_db, personal_db):
    stock = make_stock(core_db)
    make_holding(core_db, stock, quantity=10, price=100.0, currency="EUR")
    personal_db.add(StockMetadata(stock_id=stock.id, sector="Healthcare"))
    personal_db.add(StockInstrumentType(stock_id=stock.id, quote_type="EQUITY"))

    etf = make_stock(core_db)
    make_holding(core_db, etf, quantity=10, price=100.0, currency="EUR")
    personal_db.add(StockSectorWeight(stock_id=etf.id, sector="Technology", weight=1.0))
    personal_db.add(StockInstrumentType(stock_id=etf.id, quote_type="ETF"))
    personal_db.commit()

    result = compute_sector_allocation(core_db, personal_db, scope="etfs")

    assert len(result) == 1
    assert result[0]["sector"] == "Technology"


def test_scope_stocks_plus_scope_etfs_som_gelijk_aan_scope_all(core_db, personal_db):
    """Regressietest voor de exacte controle die we in de sandbox met echte
    (test-)data deden: €94.585,75 (stocks) + €38.796,30 (etfs) = €133.382,05 (all)."""
    stock = make_stock(core_db)
    make_holding(core_db, stock, quantity=3, price=150.0, currency="EUR")
    personal_db.add(StockMetadata(stock_id=stock.id, sector="Consumer Defensive"))
    personal_db.add(StockInstrumentType(stock_id=stock.id, quote_type="EQUITY"))

    etf = make_stock(core_db)
    make_holding(core_db, etf, quantity=5, price=80.0, currency="EUR")
    personal_db.add(StockSectorWeight(stock_id=etf.id, sector="Unknown", weight=1.0))
    personal_db.add(StockInstrumentType(stock_id=etf.id, quote_type="ETF"))
    personal_db.commit()

    total_all = sum(r["value_eur"] for r in compute_sector_allocation(core_db, personal_db, scope="all"))
    total_stocks = sum(r["value_eur"] for r in compute_sector_allocation(core_db, personal_db, scope="stocks"))
    total_etfs = sum(r["value_eur"] for r in compute_sector_allocation(core_db, personal_db, scope="etfs"))

    assert total_stocks + total_etfs == total_all
    assert total_all == 850.0  # 3*150 + 5*80


def test_ongeldige_scope_geeft_valueerror(core_db, personal_db):
    import pytest
    with pytest.raises(ValueError):
        compute_sector_allocation(core_db, personal_db, scope="onzin")
