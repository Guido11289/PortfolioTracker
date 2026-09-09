"""Watchlist-filtering op basis van fundamentele en koers-criteria.

CRITERIA is een registry: {naam: (veldnaam, comparator)}. Het veld kan een
kolom op StockFundamentals zijn (pe_ratio, dividend_yield, market_cap) óf
een AFGELEID veld dat we per stock uitrekenen vóór het filteren
(price_change_pct, uit WatchlistStockPrice). Voor apply_criteria() maakt
dat niets uit — het kijkt gewoon in een samengevoegde dict. Een nieuw
criterium op een BESTAAND veld toevoegen is dus altijd 1 regel; een nieuw
AFGELEID veld vereist een kleine berekeningsfunctie erbij (zoals
price_change_pct hieronder) — bewust geen automagie (§16).
"""
import operator
from datetime import datetime, timezone, timedelta
from typing import Optional

CRITERIA = {
    "pe_below": ("pe_ratio", operator.lt),
    "pe_above": ("pe_ratio", operator.gt),
    "dividend_yield_above": ("dividend_yield", operator.gt),
    "market_cap_above": ("market_cap", operator.gt),
    "market_cap_below": ("market_cap", operator.lt),
    # Koersdaling: "daalde met minstens X%" => change_pct <= -X.
    "price_drop_pct_above": ("price_change_pct", lambda value, threshold: value <= -threshold),
    # Momentum: "steeg met minstens X%" => change_pct >= X.
    "momentum_pct_above": ("price_change_pct", lambda value, threshold: value >= threshold),
}

# Criteria die price_change_pct nodig hebben — alleen voor déze rekenen we
# de prijshistorie uit (scheelt onnodige queries als er alleen op P/E
# gefilterd wordt).
_PRICE_CHANGE_CRITERIA = {"price_drop_pct_above", "momentum_pct_above"}


def compute_price_change_pct(personal_db, watchlist_stock_id: int, days: int) -> Optional[float]:
    """Procentuele verandering tussen de oudste en de nieuwste beschikbare
    sluitkoers binnen de laatste `days` dagen. None als er geen (of maar 1)
    prijspunt is — kan dan nooit aan een koerscriterium voldoen, dat is
    bewust hetzelfde principe als ontbrekende fundamentals."""
    from ..models import WatchlistStockPrice

    since = datetime.now(timezone.utc) - timedelta(days=days)
    prices = (
        personal_db.query(WatchlistStockPrice)
        .filter(WatchlistStockPrice.watchlist_stock_id == watchlist_stock_id, WatchlistStockPrice.date >= since)
        .order_by(WatchlistStockPrice.date)
        .all()
    )
    if len(prices) < 2:
        return None

    oldest, newest = prices[0].close, prices[-1].close
    if not oldest:
        return None
    return (newest - oldest) / oldest * 100


def apply_criteria(personal_db, criteria: dict, price_change_days: int = 30) -> list:
    """criteria = {"pe_below": 20, "price_drop_pct_above": 10, ...}
    (AND-logica: een aandeel moet aan ALLE opgegeven criteria voldoen).

    price_change_days bepaalt het venster voor price_drop_pct_above /
    momentum_pct_above (default 30 dagen)."""
    from ..models import WatchlistStock, StockFundamentals

    unknown = set(criteria) - set(CRITERIA)
    if unknown:
        raise ValueError(f"onbekende criteria: {sorted(unknown)}")

    needs_price_change = bool(set(criteria) & _PRICE_CHANGE_CRITERIA)

    rows = (
        personal_db.query(WatchlistStock, StockFundamentals)
        .outerjoin(StockFundamentals, StockFundamentals.watchlist_stock_id == WatchlistStock.id)
        .all()
    )

    result = []
    for stock, fundamentals in rows:
        values = {
            "pe_ratio": fundamentals.pe_ratio if fundamentals else None,
            "dividend_yield": fundamentals.dividend_yield if fundamentals else None,
            "market_cap": fundamentals.market_cap if fundamentals else None,
        }
        price_change_pct = None
        if needs_price_change:
            price_change_pct = compute_price_change_pct(personal_db, stock.id, days=price_change_days)
            values["price_change_pct"] = price_change_pct

        passes = True
        for name, threshold in criteria.items():
            field, cmp = CRITERIA[name]
            value = values.get(field)
            if value is None or not cmp(value, threshold):
                passes = False
                break
        if not passes:
            continue

        result.append({
            "id": stock.id,
            "ticker": stock.ticker,
            "name": stock.name,
            "note": stock.note,
            "price": fundamentals.price if fundamentals else None,
            "currency": fundamentals.currency if fundamentals else None,
            "pe_ratio": values["pe_ratio"],
            "dividend_yield": values["dividend_yield"],
            "market_cap": values["market_cap"],
            "price_change_pct": round(price_change_pct, 2) if price_change_pct is not None else None,
            "updated_at": fundamentals.updated_at.isoformat() if fundamentals and fundamentals.updated_at else None,
        })

    return result
