"""Read-only diagnose voor dividenddata van één fonds.

Draai (vanuit de projectroot, venv actief):
    python -m my_portfolio.scripts.diagnose_dividends "EURO STOXX"
    python -m my_portfolio.scripts.diagnose_dividends "EURO STOXX" --live
--live doet één Yahoo-call met de opgeslagen yahoo_ticker en toont wat
fetch_dividend_data() ervan maakt (schrijft niets weg).
"""
import argparse

from sqlalchemy import func

from degiro_portfolio.database import SessionLocal, Stock, Transaction
from my_portfolio.database import PersonalSessionLocal
from my_portfolio.models import DividendPayment, StockDividendInfo, StockInstrumentType

parser = argparse.ArgumentParser()
parser.add_argument("name_part")
parser.add_argument("--live", action="store_true")
args = parser.parse_args()

db, pdb = SessionLocal(), PersonalSessionLocal()
stocks = db.query(Stock).filter(Stock.name.ilike(f"%{args.name_part}%")).all()
print(f"{len(stocks)} stock(s) gevonden voor '{args.name_part}'")

for s in stocks:
    total_qty = db.query(func.sum(Transaction.quantity)).filter_by(stock_id=s.id).scalar()
    itype = pdb.query(StockInstrumentType).filter_by(stock_id=s.id).first()
    info = pdb.query(StockDividendInfo).filter_by(stock_id=s.id).first()
    print(f"\nid={s.id} naam={s.name!r} isin={s.isin} ticker={s.yahoo_ticker} cur={s.currency}")
    print(f"  quote_type={itype.quote_type if itype else None}  huidige qty={total_qty}  yield={info.dividend_yield if info else None}")

    print("  transacties:")
    for t in db.query(Transaction).filter_by(stock_id=s.id).order_by(Transaction.date):
        print(f"    {t.date:%Y-%m-%d}  qty={t.quantity}  prijs={t.price}")

    pays = pdb.query(DividendPayment).filter_by(stock_id=s.id).order_by(DividendPayment.payment_date).all()
    print(f"  DividendPayment-rijen: {len(pays)}")
    for p in pays:
        q = db.query(func.sum(Transaction.quantity)).filter(
            Transaction.stock_id == s.id, Transaction.date <= p.payment_date).scalar() or 0
        print(f"    {p.payment_date:%Y-%m-%d}  {p.amount_per_share}  {p.currency}  qty_op_datum={q}")

    if args.live:
        from my_portfolio.data.dividends import fetch_dividend_data
        data = fetch_dividend_data(s.yahoo_ticker)
        print(f"  LIVE: yield={data['dividend_yield']} cur={data['currency']} history={len(data['history'])} rijen")
        for d, amt, cur in data["history"][-8:]:
            print(f"    {d:%Y-%m-%d}  {amt}  {cur}")

db.close()
pdb.close()