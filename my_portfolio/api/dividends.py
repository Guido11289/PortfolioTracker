"""API-endpoints voor de dividendtracker."""
from typing import Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from degiro_portfolio.database import get_db

from ..database import get_personal_db
from ..analysis.dividends import (
    compute_dividend_calendar,
    compute_annual_total,
    compute_monthly_dividends,
    estimate_upcoming_annual_dividend,
)
from ..data.dividends import sync_dividend_history
from ..web.charts.dividends import build_monthly_dividend_figure

router = APIRouter()


@router.get("/dividend-calendar")
def dividend_calendar(
    response: Response,
    year: Optional[int] = None,
    core_db: Session = Depends(get_db),
    personal_db: Session = Depends(get_personal_db),
):
    response.headers["Cache-Control"] = "no-store"
    return {"payments": compute_dividend_calendar(core_db, personal_db, year=year)}


@router.get("/dividend-annual-total")
def dividend_annual_total(
    response: Response,
    year: int,
    core_db: Session = Depends(get_db),
    personal_db: Session = Depends(get_personal_db),
):
    response.headers["Cache-Control"] = "no-store"
    return {"year": year, "total_eur": compute_annual_total(core_db, personal_db, year)}


@router.get("/dividend-monthly")
def dividend_monthly(
    response: Response,
    year: int,
    core_db: Session = Depends(get_db),
    personal_db: Session = Depends(get_personal_db),
):
    response.headers["Cache-Control"] = "no-store"
    return {"year": year, "months": compute_monthly_dividends(core_db, personal_db, year)}


@router.get("/dividend-monthly/chart")
def dividend_monthly_chart(
    response: Response,
    year: int,
    core_db: Session = Depends(get_db),
    personal_db: Session = Depends(get_personal_db),
):
    response.headers["Cache-Control"] = "no-store"
    return build_monthly_dividend_figure(compute_monthly_dividends(core_db, personal_db, year), year)


@router.get("/dividend-estimate")
def dividend_estimate(
    response: Response,
    core_db: Session = Depends(get_db),
    personal_db: Session = Depends(get_personal_db),
):
    response.headers["Cache-Control"] = "no-store"
    estimates = estimate_upcoming_annual_dividend(core_db, personal_db)
    return {
        "estimates": estimates,
        "total_estimated_eur": round(sum(e["estimated_annual_dividend_eur"] for e in estimates), 2),
    }


@router.post("/sync-dividends")
def sync_dividends_endpoint(
    force: bool = False,
    core_db: Session = Depends(get_db),
    personal_db: Session = Depends(get_personal_db),
):
    """Haalt dividendhistorie + yield op via Yahoo. Kan traag zijn door de
    Yahoo rate-limiter (~3s per aandeel)."""
    return sync_dividend_history(core_db, personal_db, force=force)
