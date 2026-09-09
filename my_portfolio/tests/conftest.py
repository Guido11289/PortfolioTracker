"""Pytest-fixtures voor my_portfolio.

Belangrijk: DATABASE_URL moet gezet zijn VOORDAT degiro_portfolio.database
voor het eerst geïmporteerd wordt — die module bindt de engine bij import-
tijd (main.py:14, DATABASE_URL = get_database_url()). Vandaar dat dit op
module-niveau staat (loopt bij het laden van conftest.py, vóór de eerste
testmodule-import), niet in een fixture-functie.
"""
import os
import tempfile

_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="my_portfolio_test_")
os.close(_TMP_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB_PATH}"

import pytest

from degiro_portfolio.database import init_db, SessionLocal, Stock, Transaction, StockPrice, ExchangeRate
from my_portfolio.database import init_personal_db, PersonalSessionLocal
from my_portfolio.models import StockMetadata, StockSectorWeight, StockInstrumentType, WatchlistStock, StockFundamentals, WatchlistStockPrice


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    init_db()
    init_personal_db()
    yield
    os.remove(_TMP_DB_PATH)


@pytest.fixture
def core_db():
    """Core-sessie, leeggemaakt na elke test (geen data lekt tussen tests)."""
    session = SessionLocal()
    yield session
    session.rollback()
    for model in (Transaction, StockPrice, ExchangeRate, Stock):
        session.query(model).delete()
    session.commit()
    session.close()


@pytest.fixture
def personal_db():
    """Personal-sessie, leeggemaakt na elke test."""
    session = PersonalSessionLocal()
    yield session
    session.rollback()
    for model in (StockSectorWeight, StockMetadata, StockInstrumentType, WatchlistStockPrice, StockFundamentals, WatchlistStock):
        session.query(model).delete()
    session.commit()
    session.close()


_stock_counter = iter(range(1, 100_000))


def make_stock(core_db, **kwargs):
    """Helper: maakt een Stock-rij aan met redelijke defaults. isin/yahoo_ticker
    krijgen een oplopend nummer zodat losse aanroepen zonder expliciete
    waarden niet botsen op de unique-constraint op isin."""
    n = next(_stock_counter)
    defaults = dict(isin=f"TEST{n:07d}", name=f"Test Stock {n}", currency="EUR", yahoo_ticker=f"TST{n}")
    defaults.update(kwargs)
    stock = Stock(**defaults)
    core_db.add(stock)
    core_db.commit()
    core_db.refresh(stock)
    return stock


def make_holding(core_db, stock, quantity, price, currency=None, price_date=None):
    """Helper: geeft een Stock een holding (transactie) en een laatste koers.

    Let op: Transaction.date en StockPrice.date zijn DateTime-kolommen
    (niet Date) in de core-modellen — vandaar datetime.now(), niet
    date.today()."""
    from datetime import datetime

    when = price_date or datetime.now()
    core_db.add(Transaction(
        stock_id=stock.id, date=when,
        quantity=quantity, price=price, currency=currency or stock.currency,
    ))
    core_db.add(StockPrice(
        stock_id=stock.id, date=when,
        close=price, currency=currency or stock.currency,
    ))
    core_db.commit()
