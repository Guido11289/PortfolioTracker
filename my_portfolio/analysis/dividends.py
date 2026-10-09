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

from ..models import DividendPayment, StockDividendInfo, StockInstrumentType

def _crypto_stock_ids(personal_db: Session, stocks) -> set:
    """stock_id's van crypto-holdings: synthetische CRYPTO:-ISIN of
    quoteType CRYPTOCURRENCY (zelfde twee criteria als sector_allocation.py)."""
    stocks = list(stocks)
    ids = {s.id for s in stocks if s.isin and s.isin.startswith("CRYPTO:")}
    rest = [s.id for s in stocks if s.id not in ids]
    if rest:
        ids |= {
            t.stock_id
            for t in personal_db.query(StockInstrumentType).filter(
                StockInstrumentType.stock_id.in_(rest),
                StockInstrumentType.quote_type == "CRYPTOCURRENCY",
            )
        }
    return ids

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
    mee — je hebt ze niet ontvangen). Crypto wordt uitgesloten. year=None
    geeft alle jaren terug."""
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
    crypto_ids = _crypto_stock_ids(personal_db, stocks_by_id.values())
    rates = _exchange_rates_map(core_db)

    result = []
    for p in payments:
        stock = stocks_by_id.get(p.stock_id)
        if stock is None or p.stock_id in crypto_ids:
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

def compute_monthly_dividends(core_db: Session, personal_db: Session, year: int) -> list[dict]:
    """Ontvangen dividend per maand (EUR) voor `year`: altijd 12 rijen,
    lege maanden = 0. Per maand ook de bijdragen per aandeel (aflopend
    gesorteerd) voor de Plotly-hover."""
    from collections import defaultdict
    from datetime import datetime

    monthly = defaultdict(list)
    for row in compute_dividend_calendar(core_db, personal_db, year=year):
        month = datetime.fromisoformat(row["payment_date"]).month
        monthly[month].append({"name": row["name"], "amount_eur": round(row["amount_eur"], 2)})

    result = []
    for month in range(1, 13):
        payments = sorted(monthly.get(month, []), key=lambda p: p["amount_eur"], reverse=True)
        result.append({
            "month": month,
            "total_eur": round(sum(p["amount_eur"] for p in payments), 2),
            "payments": payments,
        })
    return result
# def compute_monthly_dividends(core_db: Session, personal_db: Session, year: int) -> list[dict]:
#     """Ontvangen dividend per maand (EUR) voor `year`: altijd 12 rijen,
#     lege maanden = 0. Aggregeert compute_dividend_calendar(), dus dezelfde
#     qty-op-ex-datum- en FX-logica (geen tweede berekening)."""
#     from datetime import datetime

#     totals = [0.0] * 12
#     for row in compute_dividend_calendar(core_db, personal_db, year=year):
#         totals[datetime.fromisoformat(row["payment_date"]).month - 1] += row["amount_eur"]
#     return [{"month": i + 1, "total_eur": round(t, 2)} for i, t in enumerate(totals)]

def estimate_upcoming_annual_dividend(core_db: Session, personal_db: Session) -> list[dict]:
    """dividend_yield x huidige waarde, per huidige niet-crypto holding.
    Zelfde waardeberekening (laatste prijs x qty x bond-scale x wisselkoers)
    als sector_allocation.py / main.py:get_portfolio_summary()."""
    holdings = (
        core_db.query(Stock, func.sum(Transaction.quantity).label("total_qty"))
        .join(Transaction, Stock.id == Transaction.stock_id)
        .group_by(Stock.id)
        .having(func.sum(Transaction.quantity) > 0)
        .all()
    )
    crypto_ids = _crypto_stock_ids(personal_db, [s for s, _ in holdings])
    holdings = [(s, q) for s, q in holdings if s.id not in crypto_ids]
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
            continue
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
def compute_monthly_dividend_forecast(
    core_db: Session, personal_db: Session, year: int,
    seasonal: bool = False, today: Optional["date"] = None,
) -> list[dict]:
    """Prognose van nog te ontvangen dividend per maand (EUR) voor `year`.

    Per huidige, niet-crypto holding met betalingen in de laatste 365 dagen:
    - betaalmaanden = de maanden waarin in die 365 dagen betaald is;
    - bedrag per betaling = mediaan van die betalingen (robuust tegen
      speciale uitkeringen) x huidige qty x laatst bekende wisselkoers;
    - seasonal=True: bedrag per share = SOM van de betalingen in dezelfde
      kalendermaand van year-1 (dekt meerdere betalingen in één maand);
      ontbreekt die, dan de mediaan. Een speciaal dividend uit year-1 komt
      dus in die maand terug.
    - alleen toekomstige maanden (huidige maand inbegrepen) en alleen als
      voor die stock die maand nog geen werkelijke betaling is ontvangen.
    Verleden jaren geven alleen nullen terug.
    """
    from collections import defaultdict
    from datetime import date, datetime, timedelta
    from statistics import median

    today = today or date.today()
    empty = [{"month": m, "total_eur": 0.0, "payments": []} for m in range(1, 13)]
    if year < today.year:
        return empty
    future_months = range(today.month, 13) if year == today.year else range(1, 13)

    holdings = (
        core_db.query(Stock, func.sum(Transaction.quantity).label("total_qty"))
        .join(Transaction, Stock.id == Transaction.stock_id)
        .group_by(Stock.id)
        .having(func.sum(Transaction.quantity) > 0)
        .all()
    )
    crypto_ids = _crypto_stock_ids(personal_db, [s for s, _ in holdings])
    current_qty = {s.id: float(q) for s, q in holdings if s.id not in crypto_ids}
    if not current_qty:
        return empty
    stocks_by_id = {s.id: s for s, _ in holdings if s.id in current_qty}

    window_start = datetime.combine(today, datetime.min.time()) - timedelta(days=365)
    query_start = min(window_start, datetime(year - 1, 1, 1)) if seasonal else window_start

    payments_by_stock = defaultdict(list)       # alleen binnen het 365-dagenvenster
    prev_year_sum = defaultdict(float)          # (stock_id, maand) -> som per share in year-1
    for p in (
        personal_db.query(DividendPayment)
        .filter(DividendPayment.payment_date >= query_start,
                DividendPayment.stock_id.in_(current_qty.keys()))
        .order_by(DividendPayment.payment_date)
    ):
        if p.payment_date >= window_start:
            payments_by_stock[p.stock_id].append(p)
        if seasonal and p.payment_date.year == year - 1 and p.amount_per_share and p.amount_per_share > 0:
            prev_year_sum[(p.stock_id, p.payment_date.month)] += p.amount_per_share

    # Al ontvangen (stock, maand)-combinaties in `year`: niet nogmaals voorspellen.
    received = {
        (row["stock_id"], datetime.fromisoformat(row["payment_date"]).month)
        for row in compute_dividend_calendar(core_db, personal_db, year=year)
    }

    rates = _exchange_rates_map(core_db)
    monthly = {m: [] for m in range(1, 13)}

    for stock_id, payments in payments_by_stock.items():
        stock = stocks_by_id[stock_id]
        amounts = [p.amount_per_share for p in payments if p.amount_per_share and p.amount_per_share > 0]
        if not amounts:
            continue

        currency = payments[-1].currency or stock.currency
        rate = rates.get(currency, _get_fallback_rate(currency))
        median_amount = median(amounts)

        for month in sorted({p.payment_date.month for p in payments}):
            if month not in future_months or (stock_id, month) in received:
                continue
            per_share = (prev_year_sum.get((stock_id, month)) if seasonal else None) or median_amount
            amount_eur = round(current_qty[stock_id] * per_share * rate, 2)
            if amount_eur > 0:
                monthly[month].append({"name": stock.name, "amount_eur": amount_eur})

    result = []
    for month in range(1, 13):
        payments = sorted(monthly[month], key=lambda p: p["amount_eur"], reverse=True)
        result.append({
            "month": month,
            "total_eur": round(sum(p["amount_eur"] for p in payments), 2),
            "payments": payments,
        })
    return result