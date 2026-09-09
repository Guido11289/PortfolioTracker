"""API voor koershistorie-backfill (data van vóór de eerste transactie)."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from degiro_portfolio.database import get_db

from ..data.price_backfill import backfill_historical_prices

router = APIRouter()


@router.post("/backfill-prices")
def backfill_prices_endpoint(
    years_back: int = 5,
    stock_id: Optional[int] = None,
    core_db: Session = Depends(get_db),
):
    """Haalt koersdata op van vóór je eerste aankoop, zodat je op de
    bestaande 'Stock Price'-grafiek (op / ) verder kunt uitzoomen. Kan
    traag zijn: elk aandeel is een aparte Yahoo-call."""
    return backfill_historical_prices(core_db, years_back=years_back, stock_id=stock_id)
