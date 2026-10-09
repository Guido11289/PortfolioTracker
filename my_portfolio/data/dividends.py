"""Ophalen van dividendhistorie + dividend_yield via Yahoo Finance.

Hergebruikt bewust `yahoo_rate_limiter` uit degiro_portfolio.price_fetchers
— zelfde reden als sector_provider.py/fundamentals_provider.py: alle
Yahoo-calls door deze app heen delen dezelfde throttle.

Geen ticker-identiteitscheck zoals sector_provider.py's _verified_ticker:
die bleek nodig voor funds_data specifiek (de Vanguard/iShares-verwisseling
die we zagen); fundamentals_provider.py doet voor gewone .info-calls ook
geen verificatie. We volgen hier dus dat (simpelere) patroon i.p.v. de
verificatielogica te dupliceren voor deze ene extra call-site.
"""
import logging
from datetime import datetime, timezone

from degiro_portfolio.price_fetchers import yahoo_rate_limiter

logger = logging.getLogger(__name__)

def fetch_dividend_data(ticker: str) -> dict:
    """Eén Yahoo-sessie per aandeel voor dividendhistorie én trailing
    dividend_yield. Geeft {"history": [(datetime, bedrag, currency), ...],
    "dividend_yield": fractie|None, "currency": str|None}. Lege history is
    normaal voor aandelen zonder dividend."""
    import yfinance as yf

    yahoo_rate_limiter.wait_if_needed()
    t = yf.Ticker(ticker)
    try:
        info = t.info
    except Exception as e:
        logger.warning("Kon info niet ophalen voor %s: %s", ticker, e)
        info = {}

    returned = str(info.get("symbol") or "").upper()
    if returned and returned != ticker.upper():
        logger.error("Yahoo gaf data voor '%s' terug terwijl '%s' was opgevraagd — genegeerd.", returned, ticker)
        return {"history": [], "dividend_yield": None, "currency": None}
    
    try:
        dividends = t.dividends
    except Exception as e:
        logger.warning("Kon dividendhistorie niet ophalen voor %s: %s", ticker, e)
        dividends = None
        

    currency = info.get("currency")
    # Yahoo's info["dividendYield"] is een percentage (0.41 = 0.41%) -> fractie.
    raw_yield = info.get("dividendYield")
    dividend_yield = float(raw_yield) / 100 if raw_yield is not None else None

    history = []
    if dividends is not None and not dividends.empty:
        for ts, amount in dividends.items():
            if amount is None:
                continue
            history.append((ts.to_pydatetime(), float(amount), currency))

    return {"history": history, "dividend_yield": dividend_yield, "currency": currency}


def sync_dividend_history(core_db, personal_db, force: bool = False) -> dict:
    """Vult DividendPayment (historie) en StockDividendInfo (yield) voor
    alle niet-crypto stocks met een yahoo_ticker. Een aandeel wordt alleen
    overgeslagen als het ZOWEL historie ALS een yield-record heeft.
    Crypto wordt nooit opgehaald; bij force=True worden eerder foutief
    opgeslagen crypto-dividendrecords verwijderd."""
    from degiro_portfolio.database import Stock
    from ..models import DividendPayment, StockDividendInfo, StockInstrumentType

    stocks = core_db.query(Stock).all()
    stocks_with_history = {
        row[0] for row in personal_db.query(DividendPayment.stock_id).distinct().all()
    }
    existing_info = {i.stock_id: i for i in personal_db.query(StockDividendInfo).all()}
    crypto_types = {
        t.stock_id for t in personal_db.query(StockInstrumentType)
        .filter(StockInstrumentType.quote_type == "CRYPTOCURRENCY")
    }

    updated, skipped, failed = 0, 0, 0
    for stock in stocks:
        has_real_isin = bool(stock.isin and str(stock.isin).strip() and not stock.isin.startswith("CRYPTO:"))
        is_crypto = bool(stock.isin and stock.isin.startswith("CRYPTO:")) or (
            not has_real_isin and stock.id in crypto_types
        )        
        if is_crypto:
            if force:
                personal_db.query(DividendPayment).filter_by(stock_id=stock.id).delete()
                personal_db.query(StockDividendInfo).filter_by(stock_id=stock.id).delete()
            skipped += 1
            continue

        has_history = stock.id in stocks_with_history
        has_info = stock.id in existing_info
        if has_history and has_info and not force:
            skipped += 1
            continue

        if not stock.yahoo_ticker:
            failed += 1
            continue

        data = fetch_dividend_data(stock.yahoo_ticker)
        if not data["history"] and data["dividend_yield"] is None:
            # Normaal niet-uitkerend aandeel, of mislukte Yahoo-call (info={}).
            failed += 1
            continue

        if data["history"]:
            if force:
                personal_db.query(DividendPayment).filter_by(stock_id=stock.id).delete()
                existing_dates = set()
            else:
                existing_dates = {
                    d for d, in personal_db.query(DividendPayment.payment_date)
                    .filter_by(stock_id=stock.id).all()
                }
            for payment_date, amount, currency in data["history"]:
                if payment_date in existing_dates:
                    continue
                personal_db.add(DividendPayment(
                    stock_id=stock.id,
                    payment_date=payment_date,
                    amount_per_share=amount,
                    currency=currency or stock.currency,
                ))

        info_record = existing_info.get(stock.id)
        if info_record is None:
            info_record = StockDividendInfo(stock_id=stock.id)
            personal_db.add(info_record)
        info_record.dividend_yield = data["dividend_yield"]
        info_record.currency = data["currency"] or stock.currency
        info_record.updated_at = datetime.now(timezone.utc)

        updated += 1

    personal_db.commit()
    return {"updated": updated, "skipped": skipped, "failed": failed, "total": len(stocks)}