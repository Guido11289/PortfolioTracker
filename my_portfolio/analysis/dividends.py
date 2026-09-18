"""Dividendkalender, jaartotaal en schatting voor huidige/historische
holdings (bewust NIET voor de watchlist — die heeft al
StockFundamentals.dividend_yield voor screening, een ander doel).

Belangrijk verschil met sector_allocation.py: een uitkering hoort bij het
aantal aandelen dat je OP DE EX-DATUM bezat (cumulatief t/m die datum via
Transaction.quantity), niet bij de huidige holding-qty — die kan sindsdien
gewijzigd zijn. Vandaar een aparte cumulatieve qty-berekening hier i.p.v.
de "huidige qty" uit sector_allocation.py.

FX: net als sector_allocation.py wordt de EUR-waarde berekend met de
LAATST BEKENDE wisselkoers uit ExchangeRate, niet de koers op de
uitkeringsdatum zelf. Bewust dezelfde, elders al aanwezige vereenvoudiging
(historische FX per dividenddatum zou een aparte databron vereisen) — niet
stilzwijgend, hier expliciet benoemd.
"""
from typing import Optional

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from degiro_portfolio.database import Stock, Transaction, StockPrice, ExchangeRate
from degiro_portfolio.main import _compute_price_scales, _get_fallback_rate

from ..models import DividendPayment, StockDividendInfo


def _exchange_rates_map(core_db: Session) -> dict:
    rates = {"EUR": 1.0}
    for r in core_db.query(ExchangeRate).all():
        rates[r.from_currency] = r.rate
    return rates


def _qty_held_at(core_db: Session, stock_id: int, at_date) -> float:
    """Cumulatieve qty t/m (inclusief) at_date — 0 of negatief als alles
    al verkocht was vóór/op de ex-datum."""
    total = (
        core_db.query(func.sum(Transaction.quantity))
        .filter(Transaction.stock_id == stock_id, Transaction.date <= at_date)
        .scalar()
    )
    return total or 0


def compute_dividend_calendar(core_db: Session, personal_db: Session, year: Optional[int] = None) -> list[dict]:
    """Eén rij per DividendPayment waarvoor je op de ex-datum een positieve
    positie had (uitkeringen tijdens periodes zonder positie tellen niet
    mee — je hebt ze niet ontvangen). year=None geeft alle jaren terug."""
    from datetime import datetime

    query = personal_db.query(DividendPayment)
    if year is not None:
        query = query.filter(
            DividendPayment.payment_date >= datetime(year, 1, 1),
            DividendPayment.payment_date < datetime(year + 1, 1, 1),
        )
    payments = query.order_by(DividendPayment.payment_date).all()
    if not payments:
        return []

    stock_ids = {p.stock_id for p in payments}
    stocks_by_id = {s.id: s for s in core_db.query(Stock).filter(Stock.id.in_(stock_ids)).all()}
    rates = _exchange_rates_map(core_db)

    result = []
    for p in payments:
        stock = stocks_by_id.get(p.stock_id)
        if stock is None:
            continue
        qty = _qty_held_at(core_db, p.stock_id, p.payment_date)
        if qty <= 0:
            continue
        currency = p.currency or stock.currency
        rate = rates.get(currency, _get_fallback_rate(currency))
        amount_eur = qty * p.amount_per_share * rate
        result.append({
            "stock_id": stock.id,
            "name": stock.name,
            "payment_date": p.payment_date.isoformat(),
            "amount_per_share": p.amount_per_share,
            "currency": currency,
            "quantity_held": qty,
            "amount_eur": round(amount_eur, 2),
        })
    return result


def compute_annual_total(core_db: Session, personal_db: Session, year: int) -> float:
    return round(sum(row["amount_eur"] for row in compute_dividend_calendar(core_db, personal_db, year=year)), 2)


def estimate_upcoming_annual_dividend(core_db: Session, personal_db: Session) -> list[dict]:
    """dividend_yield x huidige waarde, per huidige holding. Zelfde
    waardeberekening (laatste prijs x qty x bond-scale x wisselkoers) als
    sector_allocation.py / main.py:get_portfolio_summary() — bewust
    dezelfde kopie-aanpak als daar (niet geïmporteerd, want die logica zit
    in een routefunctie in de core), met dezelfde twee losstaande helpers
    hergebruikt."""
    holdings = (
        core_db.query(Stock, func.sum(Transaction.quantity).label("total_qty"))
        .join(Transaction, Stock.id == Transaction.stock_id)
        .group_by(Stock.id)
        .having(func.sum(Transaction.quantity) > 0)
        .all()
    )
    if not holdings:
        return []

    stock_ids = [s.id for s, _ in holdings]
    yield_by_stock = {
        i.stock_id: i.dividend_yield
        for i in personal_db.query(StockDividendInfo).filter(StockDividendInfo.stock_id.in_(stock_ids))
    }

    latest_date_subq = (
        core_db.query(StockPrice.stock_id, func.max(StockPrice.date).label("max_date"))
        .filter(StockPrice.stock_id.in_(stock_ids), StockPrice.close.isnot(None))
        .group_by(StockPrice.stock_id)
        .subquery()
    )
    latest_prices = (
        core_db.query(StockPrice)
        .join(latest_date_subq, and_(
            StockPrice.stock_id == latest_date_subq.c.stock_id,
            StockPrice.date == latest_date_subq.c.max_date,
        ))
        .all()
    )
    price_by_stock = {p.stock_id: p for p in latest_prices}
    rates = _exchange_rates_map(core_db)
    price_scales = _compute_price_scales(core_db, set(stock_ids))

    result = []
    for stock, qty in holdings:
        yield_frac = yield_by_stock.get(stock.id)
        if not yield_frac:
            continue  # geen bekende yield: geen schatting mogelijk (geen 0 doen alsof)
        price_record = price_by_stock.get(stock.id)
        if not price_record or not price_record.close:
            continue
        currency = price_record.currency or stock.currency
        rate = rates.get(currency, _get_fallback_rate(currency))
        value_eur = qty * price_record.close * price_scales.get(stock.id, 1.0) * rate
        result.append({
            "stock_id": stock.id,
            "name": stock.name,
            "dividend_yield": yield_frac,
            "current_value_eur": round(value_eur, 2),
            "estimated_annual_dividend_eur": round(value_eur * yield_frac, 2),
        })

    result.sort(key=lambda r: r["estimated_annual_dividend_eur"], reverse=True)
    return result
