"""Sectorweging van de huidige holdings.

De EUR-waardeberekening per aandeel (laatste prijs × shares × bond-scale ×
wisselkoers) is bewust een kopie van dezelfde logica in
degiro_portfolio.main.get_portfolio_summary() (main.py:800-811) — niet
geïmporteerd, want dat zijn regels binnen een routefunctie, geen los
importeerbare functie. De twee losstaande helpers die wél los
importeerbaar zijn (`_compute_price_scales`, `_get_fallback_rate`)
hergebruiken we wel rechtstreeks, zodat bond-scale-detectie en fallback-
koersen exact hetzelfde gedrag hebben als de rest van de app.

Gevolg: als je hier een afwijkende totale portfoliowaarde ziet t.o.v.
/api/portfolio-summary, is dat een signaal dat deze twee plekken uit
elkaar zijn gaan lopen — niet verwacht, maar wel de plek om te kijken.
"""
from collections import defaultdict
from typing import Optional

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from degiro_portfolio.database import Stock, Transaction, StockPrice, ExchangeRate
from degiro_portfolio.main import _compute_price_scales, _get_fallback_rate

from ..models import StockMetadata, StockSectorWeight, StockInstrumentType

UNKNOWN_SECTOR = "Unknown"
_FUND_QUOTE_TYPES = ("ETF", "MUTUALFUND")


def compute_sector_allocation(core_db: Session, personal_db: Session, scope: str = "all") -> list[dict]:
    """Geeft per sector: waarde in EUR, gewicht in % en het aantal holdings.

    Gewone aandelen tellen 100% mee voor hun ene sector (uit StockMetadata).
    ETF's/funds worden verdeeld over meerdere sectoren volgens hun
    fund-sectorweging (StockSectorWeight) — zie data/sector_provider.py
    voor waarom dat een apart pad nodig heeft.

    scope="all" (default): alle holdings.
    scope="stocks": alleen holdings waarvan quote_type bekend is als géén
        fund (dus expliciet EQUITY o.i.d. — nog niet-gesyncte holdings
        worden hier NIET in meegenomen, want we weten dan nog niet of het
        een fonds is).
    scope="etfs": alleen holdings met quote_type ETF/MUTUALFUND.
    """
    if scope not in ("all", "stocks", "etfs"):
        raise ValueError(f"onbekende scope: {scope!r}")

    holdings_query = (
        core_db.query(Stock, func.sum(Transaction.quantity).label("total_qty"))
        .join(Transaction, Stock.id == Transaction.stock_id)
        .group_by(Stock.id)
        .having(func.sum(Transaction.quantity) > 0)
        .all()
    )
    if not holdings_query:
        return []

    all_stock_ids = [stock.id for stock, _ in holdings_query]

    if scope != "all":
        quote_type_by_stock_id = {
            t.stock_id: t.quote_type
            for t in personal_db.query(StockInstrumentType).filter(StockInstrumentType.stock_id.in_(all_stock_ids))
        }
        if scope == "etfs":
            holdings_query = [
                (s, q) for s, q in holdings_query
                if quote_type_by_stock_id.get(s.id) in _FUND_QUOTE_TYPES
            ]
        else:  # "stocks"
            holdings_query = [
                (s, q) for s, q in holdings_query
                if s.id in quote_type_by_stock_id and quote_type_by_stock_id[s.id] not in _FUND_QUOTE_TYPES
            ]
        if not holdings_query:
            return []

    stock_ids = [stock.id for stock, _ in holdings_query]

    latest_date_subq = (
        core_db.query(StockPrice.stock_id, func.max(StockPrice.date).label("max_date"))
        .filter(StockPrice.stock_id.in_(stock_ids), StockPrice.close.isnot(None))
        .group_by(StockPrice.stock_id)
        .subquery()
    )
    latest_prices = (
        core_db.query(StockPrice)
        .join(
            latest_date_subq,
            and_(
                StockPrice.stock_id == latest_date_subq.c.stock_id,
                StockPrice.date == latest_date_subq.c.max_date,
            ),
        )
        .all()
    )
    price_by_stock = {p.stock_id: p for p in latest_prices}

    exchange_rates_map = {"EUR": 1.0}
    for r in core_db.query(ExchangeRate).all():
        exchange_rates_map[r.from_currency] = r.rate

    price_scales = _compute_price_scales(core_db, set(stock_ids))

    sector_by_stock_id: dict[int, Optional[str]] = {
        m.stock_id: m.sector
        for m in personal_db.query(StockMetadata).filter(StockMetadata.stock_id.in_(stock_ids))
    }

    # ETF/fund-sectorwegingen: stock_id -> [(sector, fractie), ...]
    fund_weights_by_stock_id: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for row in personal_db.query(StockSectorWeight).filter(StockSectorWeight.stock_id.in_(stock_ids)):
        fund_weights_by_stock_id[row.stock_id].append((row.sector, row.weight))

    sector_totals: dict[str, float] = defaultdict(float)
    sector_stock_names: dict[str, list[str]] = defaultdict(list)
    total_value = 0.0

    for stock, qty in holdings_query:
        price_record = price_by_stock.get(stock.id)
        if not price_record or not price_record.close:
            continue

        currency = price_record.currency or stock.currency
        rate = exchange_rates_map.get(currency, _get_fallback_rate(currency))
        scaled = price_record.close * price_scales.get(stock.id, 1.0)
        value_eur = qty * scaled * rate
        total_value += value_eur

        fund_weights = fund_weights_by_stock_id.get(stock.id)
        if fund_weights:
            # ETF/fund: waarde verdelen over de sectoren van het fonds.
            for sector, fraction in fund_weights:
                sector_totals[sector] += value_eur * fraction
                if stock.name not in sector_stock_names[sector]:
                    sector_stock_names[sector].append(stock.name)
        else:
            # Los aandeel (of nog geen data): 100% naar één sector.
            # Crypto heeft geen GICS-sector bij Yahoo (info["sector"]
            # ontbreekt voor CRYPTOCURRENCY-quotes) — dat weten we al aan
            # de synthetische "CRYPTO:"-ISIN (zie Config._fix_crypto_rows
            # in degiro_portfolio), dus geef het een eigen label i.p.v.
            # het generieke Unknown.
            if stock.isin and stock.isin.startswith("CRYPTO:"):
                sector = "Crypto"
            else:
                sector = sector_by_stock_id.get(stock.id) or UNKNOWN_SECTOR
            sector_totals[sector] += value_eur
            sector_stock_names[sector].append(stock.name)

    if total_value <= 0:
        return []

    result = [
        {
            "sector": sector,
            "value_eur": round(value, 2),
            "weight_pct": round(value / total_value * 100, 2),
            "num_holdings": len(sector_stock_names[sector]),
            "stocks": sorted(sector_stock_names[sector]),
        }
        for sector, value in sector_totals.items()
    ]
    result.sort(key=lambda row: row["value_eur"], reverse=True)
    return result
