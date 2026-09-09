"""Database-laag voor de personal extensie.

Belangrijk: er wordt GEEN nieuwe engine/database aangemaakt. We hergebruiken
de bestaande engine uit de core-library (degiro_portfolio.database.engine),
zodat nieuwe tabellen (later bv. StockMetadata, Watchlist) in hetzelfde
SQLite-bestand komen te staan als Stock/Transaction/StockPrice, en er dus
gewoon met SQL/ORM tussen core- en personal-tabellen gejoined kan worden
(bv. op stock_id).

We gebruiken wel een eigen `declarative_base()`, zodat personal-modellen
losstaan van de core-modellen in Python (geen wijziging aan
degiro_portfolio.database.Base nodig) — maar fysiek leven ze in dezelfde db.
"""
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from degiro_portfolio.database import engine as core_engine

# Eigen metadata/Base voor personal-modellen (nog leeg — komt in stap 2).
Base = declarative_base()

# Eigen sessionmaker, maar gebonden aan dezelfde engine/db-bestand als core.
PersonalSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=core_engine)


def init_personal_db() -> None:
    """Maak personal-tabellen aan.

    Lazy import van models: voorkomt een circulaire import (models.py
    importeert Base uit dit bestand), en zorgt dat modellen bij Base
    geregistreerd zijn vóórdat create_all() wordt aangeroepen.
    """
    from . import models  # noqa: F401  (registreert modellen bij Base)
    Base.metadata.create_all(bind=core_engine)


def get_personal_db():
    """FastAPI dependency, analoog aan degiro_portfolio.database.get_db."""
    db = PersonalSessionLocal()
    try:
        yield db
    finally:
        db.close()
