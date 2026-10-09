"""Tests voor analysis/dividends.py (maandaggregatie)."""
from datetime import datetime

from my_portfolio.analysis.dividends import compute_monthly_dividends
from my_portfolio.models import DividendPayment

from .conftest import make_stock, make_holding


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
