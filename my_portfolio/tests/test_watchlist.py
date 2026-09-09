"""Tests voor analysis/watchlist.py."""
import pytest

from my_portfolio.analysis.watchlist import apply_criteria, CRITERIA
from my_portfolio.models import WatchlistStock, StockFundamentals


def _add_watchlist_stock(personal_db, ticker, name, pe=None, div_yield=None, market_cap=None):
    entry = WatchlistStock(ticker=ticker, isin=f"ISIN-{ticker}", name=name, currency="USD")
    personal_db.add(entry)
    personal_db.commit()
    personal_db.refresh(entry)
    personal_db.add(StockFundamentals(
        watchlist_stock_id=entry.id, price=100.0, currency="USD",
        pe_ratio=pe, dividend_yield=div_yield, market_cap=market_cap,
    ))
    personal_db.commit()
    return entry


def test_geen_criteria_geeft_alles_terug(personal_db):
    _add_watchlist_stock(personal_db, "AAPL", "Apple Inc", pe=35.0)
    _add_watchlist_stock(personal_db, "XOM", "Exxon Mobil", pe=13.5)

    result = apply_criteria(personal_db, criteria={})

    assert len(result) == 2


def test_and_logica_regressietest_appel_cola_exxon(personal_db):
    """Regressietest voor het scenario dat we in de sandbox met mock-Yahoo-
    data verifieerden: van Apple/Coca-Cola/Exxon voldoet met
    pe_below=20 EN dividend_yield_above=0.02 alleen Exxon."""
    _add_watchlist_stock(personal_db, "AAPL", "Apple Inc", pe=35.0, div_yield=0.005)
    _add_watchlist_stock(personal_db, "KO", "Coca-Cola", pe=24.0, div_yield=0.031)
    _add_watchlist_stock(personal_db, "XOM", "Exxon Mobil", pe=13.5, div_yield=0.034)

    result = apply_criteria(personal_db, criteria={"pe_below": 20, "dividend_yield_above": 0.02})

    assert [r["name"] for r in result] == ["Exxon Mobil"]


def test_aandeel_zonder_fundamentals_valt_af_zodra_er_criteria_zijn(personal_db):
    entry = WatchlistStock(ticker="NEW", isin="ISIN-NEW", name="Nog niet gesynct", currency="EUR")
    personal_db.add(entry)
    personal_db.commit()
    # Bewust GEEN StockFundamentals toegevoegd.

    assert apply_criteria(personal_db, criteria={}) != []  # zonder criteria wel zichtbaar
    assert apply_criteria(personal_db, criteria={"pe_below": 999}) == []  # met criteria niet


def test_onbekend_criterium_geeft_duidelijke_fout(personal_db):
    with pytest.raises(ValueError, match="onzin_criterium"):
        apply_criteria(personal_db, criteria={"onzin_criterium": 5})


def test_market_cap_above_en_below(personal_db):
    _add_watchlist_stock(personal_db, "BIG", "Big Corp", market_cap=5e11)
    _add_watchlist_stock(personal_db, "SMALL", "Small Corp", market_cap=1e9)

    boven = apply_criteria(personal_db, criteria={"market_cap_above": 1e11})
    onder = apply_criteria(personal_db, criteria={"market_cap_below": 1e11})

    assert [r["name"] for r in boven] == ["Big Corp"]
    assert [r["name"] for r in onder] == ["Small Corp"]


def test_criteria_registry_bevat_verwachte_namen():
    """Als deze test faalt na het toevoegen van een nieuw criterium: mooi,
    dat is precies het signaal dat je de registry hebt uitgebreid — werk de
    lijst hieronder bij."""
    assert set(CRITERIA.keys()) == {
        "pe_below", "pe_above", "dividend_yield_above",
        "market_cap_above", "market_cap_below",
        "price_drop_pct_above", "momentum_pct_above",
    }


def _add_price_history(personal_db, watchlist_stock_id, prices):
    """prices = [(dagen_geleden, close), ...], oplopend in tijd te lezen
    (eerste tuple = oudste)."""
    from datetime import datetime, timezone, timedelta
    from my_portfolio.models import WatchlistStockPrice

    now = datetime.now(timezone.utc)
    for days_ago, close in prices:
        personal_db.add(WatchlistStockPrice(
            watchlist_stock_id=watchlist_stock_id,
            date=now - timedelta(days=days_ago),
            close=close,
        ))
    personal_db.commit()


def test_koersdaling_criterium_pakt_gedaalde_aandelen(personal_db):
    dropper = _add_watchlist_stock(personal_db, "DROP", "Dropper Corp")
    stable = _add_watchlist_stock(personal_db, "STBL", "Stable Corp")

    _add_price_history(personal_db, dropper.id, [(29, 100.0), (1, 85.0)])  # -15%
    _add_price_history(personal_db, stable.id, [(29, 100.0), (1, 99.0)])   # -1%

    result = apply_criteria(personal_db, criteria={"price_drop_pct_above": 10})

    assert [r["name"] for r in result] == ["Dropper Corp"]
    assert result[0]["price_change_pct"] == -15.0


def test_momentum_criterium_pakt_gestegen_aandelen(personal_db):
    riser = _add_watchlist_stock(personal_db, "RISE", "Riser Corp")
    flat = _add_watchlist_stock(personal_db, "FLAT", "Flat Corp")

    _add_price_history(personal_db, riser.id, [(29, 100.0), (1, 120.0)])  # +20%
    _add_price_history(personal_db, flat.id, [(29, 100.0), (1, 101.0)])   # +1%

    result = apply_criteria(personal_db, criteria={"momentum_pct_above": 15})

    assert [r["name"] for r in result] == ["Riser Corp"]
    assert result[0]["price_change_pct"] == 20.0


def test_geen_of_1_prijspunt_kan_koerscriterium_nooit_halen(personal_db):
    entry = _add_watchlist_stock(personal_db, "NODATA", "No Data Corp")
    _add_price_history(personal_db, entry.id, [(1, 100.0)])  # maar 1 punt

    result = apply_criteria(personal_db, criteria={"price_drop_pct_above": 0.01})

    assert result == []


def test_periode_buiten_venster_telt_niet_mee(personal_db):
    """Een prijspunt van 200 dagen geleden mag niet meetellen in een
    30-dagen-venster, ook al zou het een grote daling suggereren."""
    entry = _add_watchlist_stock(personal_db, "OLD", "Old Data Corp")
    _add_price_history(personal_db, entry.id, [(200, 200.0), (29, 100.0), (1, 99.0)])

    result = apply_criteria(personal_db, criteria={"price_drop_pct_above": 5}, price_change_days=30)

    assert result == []  # binnen de laatste 30 dagen maar -1%, niet -50%
