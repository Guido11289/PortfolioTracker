"""Diagnostische personal-endpoints.

Dit bestand bevat bewust nog geen business-functionaliteit (geen sector-
analyse, geen watchlist) — het dient alleen om te bewijzen dat de
router-mount-mechaniek op de core `app` werkt, vóórdat we op deze
architectuur nieuwe features gaan bouwen.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from degiro_portfolio.database import get_db, Stock, Transaction

from ..database import get_personal_db

router = APIRouter()


@router.get("/ping")
def personal_ping():
    """Bewijst dat de personal-router gemount is op de core-app."""
    return {"status": "ok", "layer": "personal"}


@router.get("/holdings-count")
def personal_holdings_count(db: Session = Depends(get_db)):
    """Bewijst dat personal-code de core-database (Stock/Transaction) kan
    lezen via dezelfde SQLAlchemy-modellen als main.py gebruikt."""
    total_stocks = db.query(func.count(Stock.id)).scalar()
    total_transactions = db.query(func.count(Transaction.id)).scalar()
    return {"stocks": total_stocks, "transactions": total_transactions}


@router.get("/db-check")
def personal_db_check(personal_db: Session = Depends(get_personal_db)):
    """Bewijst dat de personal-sessionmaker (eigen Base, zelfde engine)
    daadwerkelijk verbinding maakt met hetzelfde db-bestand."""
    # Nog geen personal-tabellen, dus we tonen alleen dat de sessie werkt.
    return {"status": "ok", "bind": str(personal_db.get_bind().url)}
