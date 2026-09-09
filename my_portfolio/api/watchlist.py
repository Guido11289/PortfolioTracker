"""API-endpoints voor de watchlist."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from degiro_portfolio.ticker_resolver import get_ticker_for_stock

from ..database import get_personal_db
from ..models import WatchlistStock, StockFundamentals, WatchlistStockPrice
from ..analysis.watchlist import apply_criteria, CRITERIA
from ..data.fundamentals_provider import sync_fundamentals, sync_price_history

router = APIRouter()


class AddWatchlistStock(BaseModel):
    isin: str
    name: str
    currency: str = "EUR"
    note: Optional[str] = None


@router.get("/watchlist")
def list_watchlist(response: Response, personal_db: Session = Depends(get_personal_db)):
    response.headers["Cache-Control"] = "no-store"
    return {"watchlist": apply_criteria(personal_db, criteria={})}


@router.get("/watchlist/criteria")
def list_criteria():
    """Welke criteria beschikbaar zijn — handig voor de frontend om de
    filter-UI dynamisch op te bouwen i.p.v. de namen hard te coderen."""
    return {"criteria": sorted(CRITERIA.keys())}


@router.get("/watchlist/filter")
def filter_watchlist(
    response: Response,
    pe_below: Optional[float] = None,
    pe_above: Optional[float] = None,
    dividend_yield_above: Optional[float] = None,
    market_cap_above: Optional[float] = None,
    market_cap_below: Optional[float] = None,
    price_drop_pct_above: Optional[float] = None,
    momentum_pct_above: Optional[float] = None,
    price_change_days: int = 30,
    personal_db: Session = Depends(get_personal_db),
):
    response.headers["Cache-Control"] = "no-store"
    criteria = {
        "pe_below": pe_below,
        "pe_above": pe_above,
        "dividend_yield_above": dividend_yield_above,
        "market_cap_above": market_cap_above,
        "market_cap_below": market_cap_below,
        "price_drop_pct_above": price_drop_pct_above,
        "momentum_pct_above": momentum_pct_above,
    }
    criteria = {k: v for k, v in criteria.items() if v is not None}
    return {"watchlist": apply_criteria(personal_db, criteria=criteria, price_change_days=price_change_days)}


@router.post("/watchlist")
def add_to_watchlist(payload: AddWatchlistStock, personal_db: Session = Depends(get_personal_db)):
    ticker = get_ticker_for_stock(payload.isin, payload.name, payload.currency)
    if not ticker:
        raise HTTPException(status_code=422, detail=f"Kon geen Yahoo-ticker vinden voor ISIN {payload.isin} ({payload.name})")

    existing = personal_db.query(WatchlistStock).filter_by(ticker=ticker).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"{payload.name} ({ticker}) staat al op de watchlist")

    entry = WatchlistStock(ticker=ticker, isin=payload.isin, name=payload.name, currency=payload.currency, note=payload.note)
    personal_db.add(entry)
    personal_db.commit()
    personal_db.refresh(entry)
    return {"id": entry.id, "ticker": entry.ticker, "name": entry.name}


@router.delete("/watchlist/{entry_id}")
def remove_from_watchlist(entry_id: int, personal_db: Session = Depends(get_personal_db)):
    entry = personal_db.query(WatchlistStock).filter_by(id=entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Niet gevonden")
    personal_db.query(StockFundamentals).filter_by(watchlist_stock_id=entry_id).delete()
    personal_db.query(WatchlistStockPrice).filter_by(watchlist_stock_id=entry_id).delete()
    personal_db.delete(entry)
    personal_db.commit()
    return {"status": "verwijderd", "id": entry_id}


@router.post("/watchlist/sync-fundamentals")
def sync_fundamentals_endpoint(force: bool = False, personal_db: Session = Depends(get_personal_db)):
    """Kan traag zijn door de Yahoo rate-limiter (~3s per aandeel)."""
    return sync_fundamentals(personal_db, force=force)


@router.post("/watchlist/sync-price-history")
def sync_price_history_endpoint(days: int = 90, force: bool = False, personal_db: Session = Depends(get_personal_db)):
    """Prijshistorie ophalen voor koersdaling/momentum-criteria. Los van
    sync-fundamentals omdat dit een andere Yahoo-call is (history() i.p.v.
    .info) — apart zodat je fundamentals kunt verversen zonder meteen ook
    alle prijshistorie opnieuw op te halen, en andersom."""
    return sync_price_history(personal_db, days=days, force=force)
