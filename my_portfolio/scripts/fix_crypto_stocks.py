"""Eenmalig opschoonscript, ná de crypto-import-fix.

Lost twee dingen op die zijn ontstaan door de eerdere (kapotte) crypto-
import en de eerdere (foute) ticker-resolutie:

1. Duplicate Stock-rijen per crypto-naam (bv. 2x "BITCOIN") — ontstaan
   doordat oudere imports crypto met een leeg/inconsistent ISIN opsloegen,
   terwijl nieuwere imports (na de fix) de synthetische "CRYPTO:<naam>"
   ISIN gebruiken. Transacties van de oude rij(en) worden verplaatst naar
   de rij met de "CRYPTO:"-ISIN (of, als die nog niet bestaat, naar de
   rij met de meeste transacties); de overige rijen + hun (foutieve)
   koersdata worden verwijderd.
2. Verkeerd geresolvede yahoo_ticker voor crypto (bv. een Bitcoin-ETF
   i.p.v. BTC zelf) — ticker wordt gewist zodat 'ie opnieuw resolved met
   de gepatchte ticker_resolver, en de bijbehorende (foutieve) StockPrice-
   records worden verwijderd zodat er geen ETF-koersen blijven hangen.

Draai dit ÉÉN keer na het toepassen van de core-patches:
    python -m my_portfolio.scripts.fix_crypto_stocks [--dry-run]

Ververs daarna de koersen via de bestaande "Backfill historische koersen"-
knop op de site voor elke crypto-holding (of via een normale herimport,
die roept fetch_stock_prices() automatisch aan voor stocks zonder
prijsdata).
"""
import argparse
import logging
from collections import defaultdict

from degiro_portfolio.database import SessionLocal, Stock, Transaction, StockPrice

logger = logging.getLogger(__name__)


def _is_crypto_synthetic_isin(isin) -> bool:
    return isinstance(isin, str) and isin.startswith("CRYPTO:")


def fix_crypto_stocks(dry_run: bool = False) -> None:
    session = SessionLocal()
    try:
        stocks = session.query(Stock).all()
        by_name = defaultdict(list)
        for s in stocks:
            by_name[(s.name or "").strip().upper()].append(s)

        merged_groups = 0
        for name, group in by_name.items():
            if len(group) < 2:
                continue

            # Alleen ingrijpen als er duidelijk sprake is van dezelfde
            # crypto onder meerdere rijen (minstens 1 met de synthetische
            # ISIN, of allemaal met leeg/None ISIN).
            crypto_rows = [s for s in group if _is_crypto_synthetic_isin(s.isin)]
            blank_rows = [s for s in group if not s.isin or not str(s.isin).strip()]
            if not crypto_rows and not blank_rows:
                continue  # toevallig dezelfde naam, geen crypto-duplicate

            keep = crypto_rows[0] if crypto_rows else max(
                group, key=lambda s: session.query(Transaction).filter_by(stock_id=s.id).count()
            )
            others = [s for s in group if s.id != keep.id]
            if not others:
                continue

            merged_groups += 1
            print(f"[{name}] behoud stock.id={keep.id} (isin={keep.isin!r}), "
                  f"merge/verwijder {[o.id for o in others]}")

            if not dry_run:
                for o in others:
                    moved = session.query(Transaction).filter_by(stock_id=o.id).update(
                        {"stock_id": keep.id}
                    )
                    session.query(StockPrice).filter_by(stock_id=o.id).delete()
                    session.delete(o)
                    print(f"  -> {moved} transacties verplaatst van stock.id={o.id} naar {keep.id}")

        # Ticker + koersdata resetten voor alle (overgebleven) crypto-rijen
        # zodat de gepatchte resolver ze opnieuw kan resolven.
        reset_count = 0
        for s in session.query(Stock).filter(Stock.isin.like("CRYPTO:%")).all():
            price_count = session.query(StockPrice).filter_by(stock_id=s.id).count()
            if s.yahoo_ticker or price_count:
                reset_count += 1
                print(f"[{s.name}] reset yahoo_ticker ({s.yahoo_ticker!r} -> None), "
                      f"verwijder {price_count} bestaande (mogelijk foutieve) koersrecords")
                if not dry_run:
                    s.yahoo_ticker = None
                    session.query(StockPrice).filter_by(stock_id=s.id).delete()

        if dry_run:
            session.rollback()
            print(f"\n[dry-run] {merged_groups} groep(en) zouden gemerged worden, "
                  f"{reset_count} crypto-stock(s) zouden gereset worden. Niets aangepast.")
        else:
            session.commit()
            print(f"\nKlaar: {merged_groups} groep(en) gemerged, {reset_count} crypto-stock(s) gereset.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Toon alleen wat er zou gebeuren")
    args = parser.parse_args()
    fix_crypto_stocks(dry_run=args.dry_run)
