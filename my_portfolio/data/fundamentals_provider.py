"""Fundamentele data (P/E, dividend yield, market cap) voor watchlist-
aandelen via yfinance.info.

Hergebruikt bewust `yahoo_rate_limiter` uit degiro_portfolio.price_fetchers
— zelfde reden als in sector_provider.py: alle Yahoo-calls door deze app
heen (prijzen, sectoren, fundamentals) delen dezelfde throttle.
"""
import logging
from datetime import datetime, timezone, timedelta

from degiro_portfolio.price_fetchers import yahoo_rate_limiter

logger = logging.getLogger(__name__)


def fetch_fundamentals(ticker: str) -> dict:
    """Geeft {"price", "currency", "pe_ratio", "dividend_yield", "market_cap"}
    terug. Velden die Yahoo niet heeft voor dit instrument blijven None —
    dat is normaal (bv. dividend_yield voor een aandeel zonder dividend),
    geen fout."""
    import yfinance as yf

    yahoo_rate_limiter.wait_if_needed()
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        logger.warning("Kon fundamentals niet ophalen voor %s: %s", ticker, e)
        return {}

    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        logger.warning("Yahoo geeft geen bruikbare info terug voor %s", ticker)
        return {}

    return {
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "currency": info.get("currency"),
        "pe_ratio": info.get("trailingPE"),
        "dividend_yield": info.get("dividendYield"),
        "market_cap": info.get("marketCap"),
    }


def fetch_price_history(ticker: str, days: int = 90):
    """Sluitkoersen van de laatste `days` dagen. Geeft een lijst
    [(date, close), ...] terug, oplopend gesorteerd. Hergebruikt bewust
    dezelfde provider-abstractie (get_price_fetcher) als de core-app voor
    holdings gebruikt in fetch_prices.py — niet de core fetch_stock_prices()
    zelf, want die schrijft naar de core StockPrice-tabel gekoppeld aan
    stocks.id, wat hier niet past (zie models.py-docstring bij
    WatchlistStockPrice)."""
    from degiro_portfolio.price_fetchers import get_price_fetcher

    start = datetime.now(timezone.utc) - timedelta(days=days)
    end = datetime.now(timezone.utc)

    fetcher = get_price_fetcher()
    yahoo_rate_limiter.wait_if_needed()
    try:
        df = fetcher.fetch_prices(ticker, start, end)
    except Exception as e:
        logger.warning("Kon prijshistorie niet ophalen voor %s: %s", ticker, e)
        return []

    if df is None or df.empty:
        logger.warning("Yahoo geeft geen prijshistorie terug voor %s", ticker)
        return []

    return [(idx.to_pydatetime(), float(row["close"])) for idx, row in df.iterrows() if row["close"] is not None]


def sync_price_history(personal_db, days: int = 90, force: bool = False) -> dict:
    """Vult WatchlistStockPrice voor alle watchlist-aandelen."""
    from ..models import WatchlistStock, WatchlistStockPrice

    entries = personal_db.query(WatchlistStock).all()
    has_history = {
        row[0] for row in personal_db.query(WatchlistStockPrice.watchlist_stock_id).distinct().all()
    }

    updated, skipped, failed = 0, 0, 0
    for entry in entries:
        if entry.id in has_history and not force:
            skipped += 1
            continue

        history = fetch_price_history(entry.ticker, days=days)
        if not history:
            failed += 1
            continue

        if force:
            personal_db.query(WatchlistStockPrice).filter_by(watchlist_stock_id=entry.id).delete()
        existing_dates = {
            d for d, in personal_db.query(WatchlistStockPrice.date).filter_by(watchlist_stock_id=entry.id).all()
        }
        for date, close in history:
            if date in existing_dates:
                continue
            personal_db.add(WatchlistStockPrice(watchlist_stock_id=entry.id, date=date, close=close))
        updated += 1

    personal_db.commit()
    return {"updated": updated, "skipped": skipped, "failed": failed, "total": len(entries)}


def sync_fundamentals(personal_db, force: bool = False) -> dict:
    """Vult StockFundamentals voor alle watchlist-aandelen die dat nog niet
    (recent) hebben."""
    from ..models import WatchlistStock, StockFundamentals

    entries = personal_db.query(WatchlistStock).all()
    existing = {f.watchlist_stock_id: f for f in personal_db.query(StockFundamentals).all()}

    updated, skipped, failed = 0, 0, 0
    for entry in entries:
        if entry.id in existing and not force:
            skipped += 1
            continue

        data = fetch_fundamentals(entry.ticker)
        if not data:
            failed += 1
            continue

        record = existing.get(entry.id)
        if record is None:
            record = StockFundamentals(watchlist_stock_id=entry.id)
            personal_db.add(record)

        record.price = data["price"]
        record.currency = data["currency"]
        record.pe_ratio = data["pe_ratio"]
        record.dividend_yield = data["dividend_yield"]
        record.market_cap = data["market_cap"]
        record.updated_at = datetime.now(timezone.utc)
        updated += 1

    personal_db.commit()
    return {"updated": updated, "skipped": skipped, "failed": failed, "total": len(entries)}
