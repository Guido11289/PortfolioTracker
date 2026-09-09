"""Historische koersdata ophalen van vóór de eerste transactie.

Waarom dit nodig is: degiro_portfolio.fetch_prices.fetch_stock_prices()
haalt standaard alleen prijzen op vanaf min(Transaction.date)
(fetch_prices.py:102-110) — een bewuste default in de core-library (je
wilt niet automatisch jaren aan data ophalen voor elk nieuw aandeel). Maar
de functie ondersteunt al een expliciete start_date-parameter die deze
default overschrijft, en de chart-endpoint (main.py:577-580) filtert niets
weg — hij toont gewoon alles wat in StockPrice staat. Er is dus geen
core-wijziging nodig: alleen deze functie extra aanroepen met een eerdere
start_date, vanuit de personal-laag.

fetch_stock_prices() slaat bovendien al bestaande records over per exacte
datum (fetch_prices.py:221-228, `existing = session.query(...).first()`),
dus dit is veilig herhaald aan te roepen, ook met een overlappende
periode — geen duplicaten, geen risico op het beschadigen van bestaande
data.
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def backfill_historical_prices(core_db, years_back: int = 5, stock_id: int = None) -> dict:
    """Haalt koersdata op vanaf (vandaag - years_back jaar) tot vandaag,
    voor alle huidige holdings (of één specifiek aandeel via stock_id).

    Kan traag zijn: elk aandeel is een aparte Yahoo/provider-call, met
    dezelfde rate-limiting als de rest van de app."""
    from degiro_portfolio.database import Stock, Transaction
    from degiro_portfolio.fetch_prices import fetch_stock_prices
    from sqlalchemy import func

    query = core_db.query(Stock)
    if stock_id is not None:
        query = query.filter(Stock.id == stock_id)
    stocks = query.all()

    start_date = date.today() - timedelta(days=years_back * 365)
    end_date = date.today()

    results = {}
    total_added = 0
    for stock in stocks:
        total_qty = core_db.query(func.sum(Transaction.quantity)).filter_by(stock_id=stock.id).scalar() or 0
        if total_qty <= 0:
            continue  # geen actuele holding, niet backfillen

        try:
            added = fetch_stock_prices(stock, core_db, start_date=start_date, end_date=end_date)
        except Exception as e:
            logger.warning("Backfill mislukt voor %s: %s", stock.name, e)
            added = 0
        results[stock.name] = added
        total_added += added

    return {"total_added": total_added, "per_stock": results, "start_date": start_date.isoformat()}
