"""API-endpoints voor sectoranalyse."""
from typing import Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from degiro_portfolio.database import get_db

from ..database import get_personal_db
from ..analysis.sector_allocation import compute_sector_allocation
from ..data.sector_provider import sync_sector_metadata
from ..web.charts.sector_allocation import build_sector_allocation_figure

router = APIRouter()

_SCOPE_TITLES = {
    "all": "Sectorweging — totaal",
    "stocks": "Sectorweging — losse aandelen",
    "etfs": "Sectorweging — ETF's",
}


@router.get("/sector-allocation")
def sector_allocation(
    response: Response,
    scope: Literal["all", "stocks", "etfs"] = "all",
    core_db: Session = Depends(get_db),
    personal_db: Session = Depends(get_personal_db),
):
    # Expliciet no-store: browsers cachen GET-responses soms ook als de
    # querystring verschilt (met name als een reverse proxy ertussen zit).
    # We willen hier nooit gedateerde of verkeerde scope terugkrijgen.
    response.headers["Cache-Control"] = "no-store"
    return {"allocation": compute_sector_allocation(core_db, personal_db, scope=scope)}


@router.get("/sector-allocation/chart")
def sector_allocation_chart(
    response: Response,
    scope: Literal["all", "stocks", "etfs"] = "all",
    core_db: Session = Depends(get_db),
    personal_db: Session = Depends(get_personal_db),
):
    response.headers["Cache-Control"] = "no-store"
    allocation = compute_sector_allocation(core_db, personal_db, scope=scope)
    return build_sector_allocation_figure(allocation, title=_SCOPE_TITLES[scope])


@router.post("/sync-sector-metadata")
def sync_sector_metadata_endpoint(
    force: bool = False,
    core_db: Session = Depends(get_db),
    personal_db: Session = Depends(get_personal_db),
):
    """Haalt sector/industrie op via Yahoo voor aandelen zonder metadata
    (of voor alles, met force=true). Kan traag zijn door de Yahoo
    rate-limiter (~3s per aandeel)."""
    return sync_sector_metadata(core_db, personal_db, force=force)
