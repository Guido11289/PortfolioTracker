"""Personal SQLAlchemy-modellen.

Deze modellen leven in dezelfde SQLite-db als de core-tabellen (zelfde
engine, zie database.py), maar in een eigen Base/metadata. `stock_id`
verwijst naar de bestaande `stocks.id` uit de core-library — dat werkt
prima als plain foreign key, ook al zit `Stock` in een andere Base.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, DateTime, UniqueConstraint

from .database import Base

# Let op: stock_id verwijst logisch naar degiro_portfolio.database.Stock.id,
# maar zonder SQLAlchemy ForeignKey()-object. Een cross-Base FK-constraint
# vereist dat de "stocks"-tabel bekend is in DEZE metadata (via reflectie),
# wat meer complexiteit toevoegt dan het hier oplevert (§16: geen
# over-engineering). We joinen in de analyse-laag gewoon op stock_id in
# Python/SQL — dat werkt prima zonder DB-niveau FK-afdwinging. Als je later
# écht referentiële integriteit op dit veld wilt, is
# `Base.metadata.reflect(bind=core_engine, only=["stocks"])` de aangewezen
# route — bewust nu niet gedaan.
class StockMetadata(Base):
    """Sector/industrie voor gewone aandelen (één sector per aandeel)."""

    __tablename__ = "personal_stock_metadata"
    __table_args__ = (UniqueConstraint("stock_id", name="uq_personal_stock_metadata_stock_id"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, nullable=False, index=True)
    sector = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<StockMetadata stock_id={self.stock_id} sector={self.sector!r}>"


class StockSectorWeight(Base):
    """Sectoruitsplitsing voor ETF's/funds: één aandeel kan meerdere rijen
    hebben (bv. 30% Technology, 15% Financial Services, ...). Voor gewone
    aandelen wordt deze tabel niet gebruikt — daar volstaat StockMetadata
    met weight=100%.
    """

    __tablename__ = "personal_stock_sector_weight"

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, nullable=False, index=True)
    sector = Column(String, nullable=False)
    weight = Column(Float, nullable=False)  # fractie 0.0-1.0
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<StockSectorWeight stock_id={self.stock_id} {self.sector}={self.weight:.2%}>"


class StockInstrumentType(Base):
    """quoteType per aandeel (EQUITY/ETF/MUTUALFUND/...), onafhankelijk van
    of de sector-classificatie is gelukt. Wordt bij élke sync-poging
    geschreven (ook als sector/industry/weights niet gevonden worden),
    zodat "is dit een los aandeel of een fonds" nooit afhangt van of
    Yahoo toevallig sectordata had — dat zijn twee losse vragen."""

    __tablename__ = "personal_stock_instrument_type"
    __table_args__ = (UniqueConstraint("stock_id", name="uq_personal_stock_instrument_type_stock_id"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, nullable=False, index=True)
    quote_type = Column(String, nullable=True)  # bv. "EQUITY", "ETF", "MUTUALFUND"
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<StockInstrumentType stock_id={self.stock_id} quote_type={self.quote_type!r}>"


class WatchlistStock(Base):
    """Een aandeel op de watchlist. Bewust LOS van de core Stock-tabel —
    zie het docstring-commentaar bovenaan sync_sector_metadata voor de
    parallel: net zoals daar was de verleiding om alles op stock_id te
    laten leunen, maar hier is dat inhoudelijk fout. De core Stock-tabel
    representeert "dingen die ik bezit" (holdings-queries filteren overal
    op sum(quantity) > 0); een watchlist-aandeel bezit je expliciet NIET.
    Die twee concepten samenvoegen zou ergens in de core-logica een stille
    aanname doorbreken. Vandaar een eigen, onafhankelijke identiteit hier
    (ticker/isin/naam), i.p.v. FK naar stocks.id."""

    __tablename__ = "personal_watchlist_stock"
    __table_args__ = (UniqueConstraint("ticker", name="uq_personal_watchlist_stock_ticker"),)

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False, index=True)
    isin = Column(String, nullable=True)
    name = Column(String, nullable=False)
    currency = Column(String, nullable=True)
    note = Column(String, nullable=True)
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<WatchlistStock {self.ticker} {self.name!r}>"


class StockFundamentals(Base):
    """Fundamentele data per watchlist-aandeel, apart van sectordata.
    weight/sector-tabellen hierboven horen bij holdings; dit hoort bij de
    watchlist — twee losse features, twee losse tabellen, geen gedeelde
    kolommen die toevallig hetzelfde heten maar iets anders betekenen."""

    __tablename__ = "personal_stock_fundamentals"
    __table_args__ = (UniqueConstraint("watchlist_stock_id", name="uq_personal_stock_fundamentals_watchlist_stock_id"),)

    id = Column(Integer, primary_key=True)
    watchlist_stock_id = Column(Integer, nullable=False, index=True)
    price = Column(Float, nullable=True)
    currency = Column(String, nullable=True)
    pe_ratio = Column(Float, nullable=True)
    dividend_yield = Column(Float, nullable=True)  # fractie, bv. 0.023 = 2.3%
    market_cap = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<StockFundamentals watchlist_stock_id={self.watchlist_stock_id} pe={self.pe_ratio}>"


class WatchlistStockPrice(Base):
    """Prijshistorie voor watchlist-aandelen — apart van de core
    StockPrice-tabel (die is voor holdings, gekoppeld aan stocks.id; dit is
    voor watchlist_stock_id, zelfde reden als bij StockFundamentals
    hierboven: geen kolommen die toevallig hetzelfde heten maar een andere
    betekenis dragen)."""

    __tablename__ = "personal_watchlist_stock_price"
    __table_args__ = (UniqueConstraint("watchlist_stock_id", "date", name="uq_personal_watchlist_stock_price_stock_date"),)

    id = Column(Integer, primary_key=True)
    watchlist_stock_id = Column(Integer, nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    close = Column(Float, nullable=False)

    def __repr__(self) -> str:
        return f"<WatchlistStockPrice watchlist_stock_id={self.watchlist_stock_id} {self.date}={self.close}>"


class DividendPayment(Base):
    """Eén ontvangen dividenduitkering per aandeel (holdings, niet
    watchlist — zie data/dividends.py). Net als StockMetadata een plain
    int-koppeling naar core `stocks.id`, geen ForeignKey (zelfde
    §16-afweging: geen cross-Base FK-reflectie voor dit veld)."""

    __tablename__ = "personal_dividend_payment"
    __table_args__ = (UniqueConstraint("stock_id", "payment_date", name="uq_personal_dividend_payment_stock_date"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, nullable=False, index=True)
    payment_date = Column(DateTime, nullable=False, index=True)
    amount_per_share = Column(Float, nullable=False)  # in `currency`
    currency = Column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<DividendPayment stock_id={self.stock_id} {self.payment_date}={self.amount_per_share}>"


class StockDividendInfo(Base):
    """Laatst bekende (trailing) dividend_yield per aandeel, los van de
    uitkeringshistorie in DividendPayment — nodig voor
    estimate_upcoming_annual_dividend() (yield x huidige waarde). Zelfde
    patroon als StockInstrumentType: één scalar-waarde per stock_id, altijd
    overschreven bij een sync, ongeacht of de uitkeringshistorie zelf iets
    opleverde."""

    __tablename__ = "personal_stock_dividend_info"
    __table_args__ = (UniqueConstraint("stock_id", name="uq_personal_stock_dividend_info_stock_id"),)

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, nullable=False, index=True)
    dividend_yield = Column(Float, nullable=True)  # fractie, bv. 0.021 = 2.1%
    currency = Column(String, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<StockDividendInfo stock_id={self.stock_id} yield={self.dividend_yield}>"
