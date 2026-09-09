"""Ophalen van sector/industrie-data via Yahoo Finance.

Twee soorten instrumenten, twee soorten data:
  - Gewone aandelen: één sector via yf.Ticker(ticker).info["sector"].
  - ETF's/funds: GEEN los "sector"-veld (een fund bestaat uit meerdere
    sectoren) — Yahoo geeft in plaats daarvan een sectoruitsplitsing terug
    via yf.Ticker(ticker).funds_data.sector_weightings, een dict
    {sector_code: fractie}. Dit ontdekten we doordat de eerste versie van
    deze provider alle 3 ETF's in de testportfolio als "mislukt" telde:
    yfinance vindt voor die tickers geen info["sector"], niet omdat er iets
    stuk is, maar omdat dat veld voor funds simpelweg niet bestaat.

Hergebruikt bewust `yahoo_rate_limiter` uit degiro_portfolio.price_fetchers:
dat is dezelfde Yahoo-API (undocumented rate limits), dus sector- en
prijs-calls moeten dezelfde throttle delen.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, TypedDict

from degiro_portfolio.price_fetchers import yahoo_rate_limiter

logger = logging.getLogger(__name__)

# Yahoo's fund-sectorcodes zijn snake_case (bv. "consumer_cyclical"). We
# zetten ze om naar dezelfde schrijfwijze als info["sector"] voor gewone
# aandelen (bv. "Consumer Cyclical"), zodat een ETF-sector en een
# los-aandeel-sector in dezelfde pie-chart-bucket terechtkomen.
_SECTOR_CODE_LABELS = {
    "realestate": "Real Estate",
    "consumer_cyclical": "Consumer Cyclical",
    "basic_materials": "Basic Materials",
    "consumer_defensive": "Consumer Defensive",
    "technology": "Technology",
    "communication_services": "Communication Services",
    "financial_services": "Financial Services",
    "utilities": "Utilities",
    "industrials": "Industrials",
    "energy": "Energy",
    "healthcare": "Healthcare",
}


def _label_for_sector_code(code: str) -> str:
    return _SECTOR_CODE_LABELS.get(code, code.replace("_", " ").title())


class SectorInfo(TypedDict):
    sector: Optional[str]
    industry: Optional[str]


def fetch_sector_info(ticker: str) -> SectorInfo:
    """Sector/industrie voor een gewoon aandeel (niet voor ETF's/funds —
    zie fetch_fund_sector_weights daarvoor)."""
    import yfinance as yf

    yahoo_rate_limiter.wait_if_needed()
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        logger.warning("Kon sector-info niet ophalen voor %s: %s", ticker, e)
        return {"sector": None, "industry": None}

    return {"sector": info.get("sector"), "industry": info.get("industry")}


def fetch_fund_sector_weights(ticker: str) -> dict:
    """Sectoruitsplitsing voor een ETF/fund. Geeft {} terug bij fouten of
    als het instrument geen fund-sectordata heeft — logt in beide gevallen
    WAAROM, want stil {} teruggeven maakt "geen data bij Yahoo" en "een bug"
    onmogelijk uit elkaar te houden."""
    import yfinance as yf

    yahoo_rate_limiter.wait_if_needed()
    try:
        raw_weights = yf.Ticker(ticker).funds_data.sector_weightings
    except Exception as e:
        logger.warning("Kon fund-sectorweging niet ophalen voor %s: %s", ticker, e)
        return {}

    if not raw_weights:
        logger.warning(
            "Yahoo geeft geen sector_weightings terug voor %s (fund_data "
            "geen exception, maar leeg/None: %r) — vermoedelijk heeft "
            "Yahoo deze data niet voor dit specifieke fonds (komt vaker "
            "voor bij Europese UCITS-ETF's dan bij Amerikaanse funds).",
            ticker, raw_weights,
        )
        return {}

    total = sum(raw_weights.values())
    if total <= 0:
        logger.warning("sector_weightings voor %s somt op tot %s (<=0), genegeerd", ticker, total)
        return {}

    # Normaliseren naar som=1.0 (Yahoo's weights tellen soms niet precies
    # tot 100% op door cash/overige posities in het fund).
    return {_label_for_sector_code(code): fraction / total for code, fraction in raw_weights.items()}


def fetch_fund_top_holdings(ticker: str) -> list:
    """Top-holdings van een fund: [(symbol, name, weight_fractie), ...].

    Andere databron dan sector_weightings (aparte Yahoo-velden, apart
    gevuld) — dit is dus een écht onafhankelijke fallback, geen herhaling
    van dezelfde lege data."""
    import yfinance as yf

    yahoo_rate_limiter.wait_if_needed()
    try:
        df = yf.Ticker(ticker).funds_data.top_holdings
    except Exception as e:
        logger.warning("Kon top_holdings niet ophalen voor %s: %s", ticker, e)
        return []

    if df is None or df.empty:
        logger.warning("Yahoo geeft geen top_holdings terug voor %s", ticker)
        return []

    return [
        (symbol, row["Name"], float(row["Holding Percent"]))
        for symbol, row in df.iterrows()
    ]


def fetch_fund_sector_weights_via_holdings(ticker: str) -> dict:
    """Fallback wanneer sector_weightings leeg is: bereken de sectorweging
    zelf uit de top-holdings, door van élk bedrijf in de top-10 de sector
    op te zoeken (hergebruikt fetch_sector_info — dezelfde functie als voor
    gewone aandelen) en te wegen met het holding-percentage.

    Let op: top_holdings dekt meestal niet 100% van het fonds (bv. top 10
    van een breed indexfonds is vaak maar 20-30%). Het niet-gedekte deel
    komt in de "Unknown"-bucket terecht — dat is een bewuste, zichtbare
    keuze (liever een deel Unknown dan een misleidende 100%-projectie op
    basis van 10 bedrijven)."""
    holdings = fetch_fund_top_holdings(ticker)
    if not holdings:
        return {}

    sector_totals: dict = {}
    covered = 0.0
    for symbol, name, weight in holdings:
        info = fetch_sector_info(symbol)
        sector = info["sector"] or "Unknown"
        sector_totals[sector] = sector_totals.get(sector, 0.0) + weight
        covered += weight

    if covered < 1.0:
        sector_totals["Unknown"] = sector_totals.get("Unknown", 0.0) + (1.0 - covered)

    logger.warning(
        "%s: sectorweging afgeleid uit top-%d holdings (dekking %.0f%%)",
        ticker, len(holdings), covered * 100,
    )
    return sector_totals


def _is_fund(info: dict) -> bool:
    return info.get("quoteType") in ("ETF", "MUTUALFUND")


def sync_sector_metadata(core_db, personal_db, force: bool = False) -> dict:
    """Vult StockMetadata (gewone aandelen) of StockSectorWeight (ETF's/
    funds) voor alle stocks die dat nog niet hebben.

    `core_db` / `personal_db` zijn losse sessies (core-modellen resp.
    personal-modellen) — zie api/sector.py voor hoe ze binnenkomen.
    """
    import yfinance as yf

    from degiro_portfolio.database import Stock
    from ..models import StockMetadata, StockSectorWeight, StockInstrumentType

    stocks = core_db.query(Stock).all()
    existing_single = {m.stock_id for m in personal_db.query(StockMetadata).all()}
    existing_weighted = {
        row[0] for row in personal_db.query(StockSectorWeight.stock_id).distinct().all()
    }
    existing_types = {t.stock_id: t for t in personal_db.query(StockInstrumentType).all()}

    updated, skipped, failed = 0, 0, 0
    for stock in stocks:
        has_sector_data = stock.id in existing_single or stock.id in existing_weighted
        has_type_data = stock.id in existing_types
        # Pas overslaan als ZOWEL sectordata als instrument-type al bekend
        # zijn — anders blijft quote_type onbekend voor aandelen die vóór
        # de introductie van StockInstrumentType al gesynchroniseerd waren.
        if has_sector_data and has_type_data and not force:
            skipped += 1
            continue

        if not stock.yahoo_ticker:
            failed += 1
            continue

        yahoo_rate_limiter.wait_if_needed()
        try:
            info = yf.Ticker(stock.yahoo_ticker).info
        except Exception as e:
            logger.warning("Kon quoteType niet bepalen voor %s: %s", stock.yahoo_ticker, e)
            failed += 1
            continue

        # quoteType altijd vastleggen, los van of sector-classificatie lukt
        # — "is dit een fonds" moet blijven werken ook als Yahoo geen
        # sectordata heeft voor dit specifieke instrument.
        type_record = existing_types.get(stock.id)
        if type_record is None:
            type_record = StockInstrumentType(stock_id=stock.id)
            personal_db.add(type_record)
        type_record.quote_type = info.get("quoteType")
        type_record.updated_at = datetime.now(timezone.utc)

        if _is_fund(info):
            # info-niveau logging komt in de praktijk vaak niet door (geen
            # basicConfig ingesteld) — warning gebruiken zodat dit gegarandeerd
            # zichtbaar is tijdens het debuggen, ook zonder extra log-config.
            logger.warning("%s herkend als fund (quoteType=%s), haal sectorweging op", stock.yahoo_ticker, info.get("quoteType"))
            weights = fetch_fund_sector_weights(stock.yahoo_ticker)
            if not weights:
                logger.warning("%s: sector_weightings leeg, val terug op top-holdings-methode", stock.yahoo_ticker)
                weights = fetch_fund_sector_weights_via_holdings(stock.yahoo_ticker)
            if not weights:
                failed += 1
                continue
            personal_db.query(StockSectorWeight).filter_by(stock_id=stock.id).delete()
            for sector, fraction in weights.items():
                personal_db.add(StockSectorWeight(stock_id=stock.id, sector=sector, weight=fraction))
            updated += 1
        else:
            sector, industry = info.get("sector"), info.get("industry")
            if sector is None and industry is None:
                logger.warning(
                    "%s: geen fund (quoteType=%s) maar ook geen sector/industry "
                    "in info — mislukt", stock.yahoo_ticker, info.get("quoteType"),
                )
                failed += 1
                continue
            record = personal_db.query(StockMetadata).filter_by(stock_id=stock.id).first()
            if record is None:
                record = StockMetadata(stock_id=stock.id)
                personal_db.add(record)
            record.sector = sector
            record.industry = industry
            record.updated_at = datetime.now(timezone.utc)
            updated += 1

    personal_db.commit()
    return {"updated": updated, "skipped": skipped, "failed": failed, "total": len(stocks)}
