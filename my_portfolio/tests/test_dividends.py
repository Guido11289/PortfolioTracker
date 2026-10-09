"""Tests voor analysis/dividends.py (maandaggregatie)."""
from datetime import date, datetime
import pytest

from my_portfolio.analysis.dividends import compute_monthly_dividends, compute_monthly_dividend_forecast
from my_portfolio.models import DividendPayment, StockInstrumentType

from .conftest import make_stock, make_holding

TODAY = date(2026, 6, 10)   # venster = 2025-06-10 t/m 2026-06-10


def _holding_with_payments(core_db, personal_db, payments, qty=10, **stock_kw):
    s = make_stock(core_db, **stock_kw)
    make_holding(core_db, s, quantity=qty, price=100.0, currency="EUR", price_date=datetime(2024, 1, 1))
    for d, a in payments:
        personal_db.add(DividendPayment(stock_id=s.id, payment_date=d, amount_per_share=a, currency="EUR"))
    personal_db.commit()
    return s

def _forecast(core_db, personal_db, year=2026, seasonal=False):
    rows = compute_monthly_dividend_forecast(core_db, personal_db, year, seasonal=seasonal, today=TODAY)
    return {r["month"]: r["total_eur"] for r in rows}


def test_maandtotalen_en_positie_op_exdatum(core_db, personal_db):
    s = make_stock(core_db)
    make_holding(core_db, s, quantity=10, price=100.0, currency="EUR", price_date=datetime(2024, 1, 1))
    for d, a in [(datetime(2023, 12, 1), 9.0),   # vóór aankoop: telt niet
                 (datetime(2024, 3, 15), 0.5), (datetime(2024, 3, 20), 0.5),
                 (datetime(2024, 6, 15), 1.0)]:
        personal_db.add(DividendPayment(stock_id=s.id, payment_date=d, amount_per_share=a, currency="EUR"))
    personal_db.commit()

    months = compute_monthly_dividends(core_db, personal_db, 2024)

    assert len(months) == 12
    assert months[2]["total_eur"] == 10.0   # maart
    assert months[5]["total_eur"] == 10.0   # juni
    assert sum(m["total_eur"] for m in months) == 20.0


def test_jaar_zonder_uitkeringen_geeft_12_nullen(core_db, personal_db):
    months = compute_monthly_dividends(core_db, personal_db, 2024)

    assert len(months) == 12
    assert all(m["total_eur"] == 0 for m in months)


def test_forecast_kwartaalbetaler_mediaan_en_huidige_maand_al_ontvangen(core_db, personal_db):
    _holding_with_payments(core_db, personal_db, [
        (datetime(2025, 6, 15), 0.20), (datetime(2025, 9, 15), 0.30), (datetime(2025, 12, 15), 0.10),
        (datetime(2026, 3, 15), 0.25), (datetime(2026, 6, 5), 0.25),   # juni 2026 al ontvangen
    ])
    m = _forecast(core_db, personal_db)  # mediaan van [.2,.3,.1,.25,.25] = 0.25 -> 2.5
    assert m[6] == 0.0                   # huidige maand al ontvangen -> niet dubbel
    assert m[9] == pytest.approx(2.5)
    assert m[12] == pytest.approx(2.5)
    assert m[3] == 0.0                   # verleden maand


def test_forecast_seizoensgebonden_gebruikt_zelfde_maand_vorig_jaar(core_db, personal_db):
    _holding_with_payments(core_db, personal_db, [
        (datetime(2025, 6, 15), 0.20), (datetime(2025, 9, 15), 0.30), (datetime(2025, 12, 15), 0.10),
        (datetime(2026, 3, 15), 0.25), (datetime(2026, 6, 5), 0.25),
    ])
    m = _forecast(core_db, personal_db, seasonal=True)
    assert m[6] == 0.0
    assert m[9] == pytest.approx(3.0)
    assert m[12] == pytest.approx(1.0)


def test_forecast_huidige_maand_nog_niet_ontvangen_telt_mee(core_db, personal_db):
    _holding_with_payments(core_db, personal_db, [(datetime(2025, 6, 15), 0.5)])
    assert _forecast(core_db, personal_db)[6] == pytest.approx(5.0)
    assert _forecast(core_db, personal_db, seasonal=True)[6] == pytest.approx(5.0)


def test_forecast_speciaal_dividend_gedempt_door_mediaan_maar_niet_seizoensgebonden(core_db, personal_db):
    _holding_with_payments(core_db, personal_db, [
        (datetime(2025, 7, 10), 0.20), (datetime(2025, 10, 10), 0.20),
        (datetime(2025, 12, 1), 2.00),                                  # speciaal
        (datetime(2026, 1, 10), 0.20), (datetime(2026, 4, 10), 0.20),
    ])
    median_mode = _forecast(core_db, personal_db)
    seasonal_mode = _forecast(core_db, personal_db, seasonal=True)
    assert median_mode[12] == pytest.approx(2.0)     # mediaan 0.20 -> speciaal gedempt
    assert seasonal_mode[12] == pytest.approx(20.0)  # gedrag: speciaal komt terug in zijn maand
    assert seasonal_mode[7] == pytest.approx(2.0)
    assert seasonal_mode[10] == pytest.approx(2.0)


def test_forecast_seizoen_fallback_op_mediaan_zonder_vorig_jaar_bedrag(core_db, personal_db):
    # year=2027 -> referentiejaar 2026: maart heeft een bedrag, december niet.
    _holding_with_payments(core_db, personal_db, [
        (datetime(2025, 12, 15), 0.10), (datetime(2026, 3, 15), 0.30),
    ])
    m = _forecast(core_db, personal_db, year=2027, seasonal=True)
    assert m[3] == pytest.approx(3.0)    # 2026-maart
    assert m[12] == pytest.approx(2.0)   # fallback: mediaan(0.1, 0.3) = 0.2


def test_forecast_meerdere_betalingen_in_dezelfde_maand(core_db, personal_db):
    _holding_with_payments(core_db, personal_db, [
        (datetime(2026, 3, 5), 0.10), (datetime(2026, 3, 25), 0.15),
    ])
    assert _forecast(core_db, personal_db, year=2027, seasonal=True)[3] == pytest.approx(2.5)   # som
    assert _forecast(core_db, personal_db, year=2027, seasonal=False)[3] == pytest.approx(1.25)  # bestaand gedrag: 1x mediaan


def test_forecast_sluit_crypto_met_synthetisch_isin_uit(core_db, personal_db):
    _holding_with_payments(core_db, personal_db, [(datetime(2025, 9, 15), 0.5)], isin="CRYPTO:BITCOIN")
    assert sum(_forecast(core_db, personal_db).values()) == 0.0


def test_forecast_sluit_cryptocurrency_quote_type_uit_zonder_isin(core_db, personal_db):
    s = _holding_with_payments(core_db, personal_db, [(datetime(2025, 9, 15), 0.5)], isin=None)
    personal_db.add(StockInstrumentType(stock_id=s.id, quote_type="CRYPTOCURRENCY"))
    personal_db.commit()
    assert sum(_forecast(core_db, personal_db).values()) == 0.0


def test_forecast_echt_isin_wint_van_cryptocurrency_quote_type(core_db, personal_db):
    """Regressie: ETF met foutief opgeslagen quote_type CRYPTOCURRENCY."""
    s = _holding_with_payments(core_db, personal_db, [(datetime(2025, 9, 15), 0.5)])  # echt ISIN uit make_stock
    personal_db.add(StockInstrumentType(stock_id=s.id, quote_type="CRYPTOCURRENCY"))
    personal_db.commit()
    assert _forecast(core_db, personal_db)[9] == pytest.approx(5.0)