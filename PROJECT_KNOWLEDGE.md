# Project Knowledge — DEGIRO Portfolio Tracker: Personal Extension

## Wat dit project is

Uitbreiding van de open-source `degiro_portfolio`-library
(https://github.com/jdrumgoole/degiro_portfolio, pip-installeerbaar als
`degiro_portfolio`) met persoonlijke functionaliteit: sectoranalyse,
watchlist, koershistorie-backfill, crypto-support. Repo:
https://github.com/Guido11289/PortfolioTracker

Uitbreidingen zitten in het losse `my_portfolio`-package. De core-library
wordt **liever niet** aangepast, maar waar dat aantoonbaar niet anders kan
(zie §"Core-patches") wordt ze gepatcht via een versie-gepinde patchfile.

## Architectuurprincipe

**Volgorde van voorkeur bij elke nieuwe wens:**
1. Oplossen binnen `my_portfolio/` (eigen laag, hergebruik van core-
   functies/helpers).
2. Runtime-injectie in `server.py` (core-HTML live van disk lezen +
   kleine vaste blokken injecteren; nooit een gekopieerd/gefixeerd
   bestand).
3. **Pas als 1 en 2 niet kunnen** (bv. kolomtype in de core-DB, import-
   parsing, ticker-resolutie-logica): core-patch. Dan verplicht: patch
   regenereren, `docs/LIBRARY_CHANGES.md` bijwerken, in dit document
   benoemen waarom het niet anders kon.

`my_portfolio/server.py` importeert de FastAPI `app` uit
`degiro_portfolio.main` en verrijkt dat object at runtime:
- `app.include_router(...)` voor nieuwe API-endpoints (`/api/personal/*`)
- Nieuwe routes (`/personal`, `/watchlist`) voor eigen pagina's
- De `/`-route wordt vervangen door een functie die `static/index.html`
  **live van disk leest** en er per request kleine, vaste HTML/JS-blokken
  in injecteert (nav-link, backfill-knop, chart-range-fix). Geen fork van
  dat bestand.

Start: `python -m uvicorn my_portfolio.server:app --host 127.0.0.1 --port 8000`
i.p.v. `python -m degiro_portfolio` (dat start de kale core-app).

**Env-var gotcha:** database-locatie via `DATABASE_URL` (in
`degiro_portfolio/database.py`), NIET `DEGIRO_PORTFOLIO_DB` (staat in
`config.py` maar wordt nergens gebruikt — dode config in de core, niet
gefixt).

## Core-patches (crypto-support e.d.)

**Waarom nodig:** DEGIRO laat bij crypto-trades ISIN én Quantity leeg, en
crypto-hoeveelheden zijn fractioneel, terwijl de core `quantity` als
`Integer` opslaat en `int()`-casts gebruikt. Dat zit in kolomtypes,
importparsing en ticker-resolutie van de core zelf — niet op te lossen
vanuit `my_portfolio/` of via HTML-injectie.

**Mechanisme:**
- `patches/degiro_portfolio-0.5.13.patch` — de patch zelf (git-formaat).
- `my_portfolio/scripts/apply_library_patches.py` — past de patch toe op de
  geïnstalleerde library:
  - weigert te draaien als `degiro_portfolio` niet exact **0.5.13** is;
  - controleert eerst of de patch schoon past, past dan alles-of-niets toe;
  - idempotent (nogmaals draaien = "al toegepast");
  - exit 1 en library ongemoeid als de patch niet past;
  - modi: (default) toepassen, `--check` (exit 0 = toegepast), `--revert`.
  - gebruikt `git` (PATH) alleen als patch-tool.
  - Draaien: `python -m my_portfolio.scripts.apply_library_patches`
- `requirements.txt` pint `degiro_portfolio==0.5.13`.
- `docs/LIBRARY_CHANGES.md` — leesbare diff, gegenereerd door
  `my_portfolio/scripts/audit_library_changes.py` (diff lokaal geïnstalleerd
  vs originele PyPI-wheel van dezelfde versie). Exit code 1 van dat script
  is normaal (er ZIJN verschillen).

**Na `pip install --upgrade`, `--force-reinstall` of een nieuwe venv zijn
de patches weg** → `apply_library_patches` opnieuw draaien. Een nieuwere
library-versie wordt door het script geweigerd tot er een nieuwe patch voor
is gemaakt (eerst `audit_library_changes` om te zien wat upstream al zelf
oplost).

**Inhoud van de patch (7 bestanden):**

| Bestand | Wijziging |
|---|---|
| `config.py` | 17-kolommen-export ondersteund; `_fix_crypto_rows()`: crypto-rijen (leeg ISIN + leeg Quantity) → quantity teruggerekend uit value_eur/price, ISIN `CRYPTO:<PRODUCTNAAM>` |
| `database.py` | `Transaction.quantity` Integer → Float |
| `import_data.py` | `int(quantity)` → `float(quantity)` |
| `fetch_prices.py` | startdatum 10 dagen vóór eerste transactie |
| `main.py` | `int(qty)`-casts weg, `timedelta`-import, 10 dagen extra prijshistorie |
| `static/index.html` | performance-%-grafiek onder portfoliowaarde + markers bij nieuwe investeringen |
| `ticker_resolver.py` | `resolve_crypto_ticker()` (quoteType CRYPTOCURRENCY, `<ROOT>-EUR` verifiëren) + crypto-pad in `get_ticker_for_stock()` voor `CRYPTO:`-ISIN's |

Let op: de performance-grafiek en 10-dagen-padding staan los van crypto,
maar zitten in dezelfde patch-set.

**Code in `my_portfolio/` die op de patches leunt:**
- `analysis/sector_allocation.py`: crypto → eigen sector "Crypto" (via
  `quoteType == "CRYPTOCURRENCY"` of ISIN-prefix `CRYPTO:`); Yahoo heeft
  geen GICS-sector voor crypto.
- `scripts/fix_crypto_stocks.py` (`--dry-run`): eenmalig opschoonscript
  voor duplicate crypto-Stock-rijen en foutief geresolvede tickers uit de
  periode vóór de patches. Draaien ná het toepassen van de patches;
  daarna koersen verversen via de backfill-knop.

**Bekende verouderde teksten in de code (nog bij te werken):**
- Docstring in `server.py` ("Geen enkel bestand in de geïnstalleerde
  library wordt aangepast") klopt niet meer.
- `audit_library_changes.py` genereert een ⚠️-kop die zegt dat wijzigingen
  "bij de volgende upgrade verdwijnen en teruggeport moeten worden"; sinds
  het patch-mechanisme is dat achterhaald (nu: patch opnieuw toepassen).
- `docs/LIBRARY_CHANGES.md` bevat een absoluut lokaal pad; alleen die regel
  mag verschillen bij hergenereren.

## Laagstructuur per feature

```
my_portfolio/
├── server.py          # mount routers, injecteert in core-HTML
├── database.py         # eigen Base, hergebruikt core engine (zelfde db-bestand)
├── models.py            # alle personal-tabellen
├── desktop.py            # pywebview-wrapper (optioneel)
├── data/                  # externe data ophalen (Yahoo via yfinance)
├── analysis/               # pure berekeningen, geen FastAPI/DB-koppeling
├── api/                     # dunne FastAPI-routers, roepen analysis/ aan
├── web/                      # HTML-pagina's + charts/
├── scripts/                   # eenmalige/diagnostische CLI-tools
└── tests/                      # pytest, eigen tijdelijke db per testrun
patches/                         # library-patch(es), versie-gepind
docs/                             # LIBRARY_CHANGES.md (gegenereerd)
```

Voor elke nieuwe feature: `data → analysis → api → web`. Analyse bevat de
rekenlogica en is los getest; API is een dunne doorgeefluik; visualisatie
bevat geen berekeningen.

## Datamodellen (personal, eigen Base, zelfde SQLite-bestand als core)

- `StockMetadata` — sector/industry voor gewone aandelen (koppelt aan core
  `stocks.id` via plain int, GEEN SQLAlchemy ForeignKey — cross-Base FK
  vereist reflectie, bewust niet gedaan, §16 geen over-engineering)
- `StockSectorWeight` — sectoruitsplitsing voor ETF's/funds (meerdere rijen
  per aandeel, weight-fractie)
- `StockInstrumentType` — quoteType (EQUITY/ETF/MUTUALFUND/CRYPTOCURRENCY)
  per aandeel, LOS van of sectorclassificatie lukte — nodig om op
  "stocks"/"etfs" te filteren ook zonder Yahoo-sectordata
- `WatchlistStock` — bewust NIET gekoppeld aan core `Stock` (die tabel
  = "wat ik bezit"); eigen ticker/isin/naam
- `StockFundamentals` — P/E, dividend yield, market cap per watchlist-aandeel
- `WatchlistStockPrice` — prijshistorie watchlist (los van core `StockPrice`)
- `DividendPayment` — één uitkering per aandeel (holdings, niet watchlist).
  `payment_date` is in feite de EX-datum (yfinance). Unique op
  (stock_id, payment_date). Plain int-koppeling naar `stocks.id`, geen FK.
- `StockDividendInfo` — laatst bekende trailing dividend_yield (fractie) per
  aandeel, los van de uitkeringshistorie. Altijd overschreven bij een sync.

## Features — huidige status

### 1. Sectoranalyse (`/personal`)
- 3 pies: losse aandelen / ETF's / totaal (`scope=all|stocks|etfs`)
- Gewone aandelen: `yf.Ticker(t).info["sector"]`; crypto: bucket "Crypto"
- ETF's: eerst `funds_data.sector_weightings` (vaak LEEG voor Europese
  UCITS-ETF's — Yahoo-datadekking, geen bug); fallback: top-10 holdings →
  sector per bedrijf, gewogen met holding-%. Niet-gedekt deel → "Unknown"
  (bewust zichtbaar i.p.v. extrapoleren).
- **Opgeloste bug — Yahoo/yfinance dataverwisseling:** twee verschillende
  ETF's (Vanguard S&P 500, iShares AEX) kregen in dezelfde sync-run
  identieke sectorwegingen (data van het verkeerde ticker bij opeenvolgende
  `Ticker()`-calls). Fix: `_verified_ticker()` in `data/sector_provider.py`
  checkt `info['symbol']` tegen het opgevraagde ticker; bij mismatch wordt
  de data genegeerd en gelogd.
  - `scripts/diagnose_sector_data.py` — read-only dump van sector-tabellen.
  - `scripts/reset_sector_data.py` — wist StockMetadata/StockSectorWeight/
    StockInstrumentType zodat een her-sync schone data ophaalt (eenmalig;
    daarna "Sync sector-data" of `POST /api/personal/sync-sector-metadata?force=true`).
- Waardeberekening (shares × koers × bond-scale × wisselkoers) is een
  bewuste KOPIE van `main.py:get_portfolio_summary()` (zit in een
  routefunctie, niet importeerbaar) — bij core-update handmatig
  synchroniseren. `_compute_price_scales` en `_get_fallback_rate` worden
  wél rechtstreeks hergebruikt. Afwijking t.o.v. `/api/portfolio-summary`
  = signaal dat ze uit elkaar lopen.

### 2. Watchlist (`/watchlist`)
- Toevoegen via ISIN, hergebruikt `ticker_resolver.get_ticker_for_stock()`
- Criteria-registry `CRITERIA` in `analysis/watchlist.py` (naam → (veld,
  comparator)); nieuw criterium op bestaand veld = 1 regel. Huidig:
  pe_below/above, dividend_yield_above, market_cap_above/below,
  price_drop_pct_above, momentum_pct_above (laatste 2 AFGELEID uit
  `WatchlistStockPrice` binnen instelbaar venster, `compute_price_change_pct`)
- AND-logica; aandeel zonder fundamentals/koersdata valt af zodra er
  criteria zijn.
- Prijshistorie via `price_fetchers.get_price_fetcher()` (provider-
  abstractie), niet via core `fetch_stock_prices()` (gekoppeld aan core
  `StockPrice`).

### 3. Koershistorie-backfill
- `data/price_backfill.py` roept `fetch_stock_prices(stock, session,
  start_date=...)` aan met eerdere `start_date` (default core =
  `min(Transaction.date)`). Idempotent (slaat bestaande datums over). Alleen
  holdings met qty > 0.
- Knop GEÏNJECTEERD direct onder de "Stock Price"-grafiek op `/`;
  `POST /api/personal/backfill-prices?years_back=5&stock_id=...`

### 4. Chart-range-fix (standaard-view + zoom-behoud)
- `Plotly.newPlot` gewrapt (client-side, geïnjecteerd) voor containers
  `'chart'` en `'index-chart'`; `renderChart(data)` ook gewrapt om de
  ONGEFILTERDE `data.transactions` te lezen (de core filtert de Buy-trace
  op currency → bij mismatch leeg).
- Y-as zelf berekend uit datapunten in het x-venster (Plotly `autorange`
  deed dit niet).
- NIEUW aandeel: standaard-view (eerste aankoop → nu). REDRAW zelfde
  aandeel (core auto-refresh per minuut): zoomstand terugleest uit
  `element.layout` zodat handmatige zoom behouden blijft.

### 5. Dividenden (`/dividends`)
- `data/dividends.py`: `fetch_dividend_data` (één Yahoo-sessie: `.info` +
  `.dividends`), met symbol-verificatie tegen het opgevraagde ticker (zelfde
  reden als `_verified_ticker`). yfinance `dividendYield` is een percentage
  -> delen door 100. `sync_dividend_history`: slaat alleen over als ZOWEL
  historie ALS yield-record bestaat; crypto wordt nooit opgehaald, bij
  `force=True` worden foutieve crypto-dividendrecords verwijderd.
- **Crypto-regel (data + analysis):** een echt ISIN wint van quote_type.
  Crypto = ISIN-prefix `CRYPTO:`, of quote_type CRYPTOCURRENCY alleen voor
  stocks ZONDER ISIN. Reden: een fout opgeslagen quote_type (ETF als
  CRYPTOCURRENCY) wiste eerder dividenddata van een ETF.
  `_crypto_stock_ids` (analysis) en `is_crypto` (data) moeten gelijk blijven.
- `analysis/dividends.py`:
  - `compute_dividend_calendar`: aantal = cumulatieve qty t/m de ex-datum
    (niet de huidige qty); uitkeringen zonder positie tellen niet. EUR met
    de LAATST BEKENDE wisselkoers, niet de koers op de datum (bewuste
    vereenvoudiging, zelfde als sector_allocation).
  - `compute_monthly_dividends`: altijd 12 rijen, met bijdragen per aandeel.
  - `estimate_upcoming_annual_dividend`: yield x huidige waarde.
  - `compute_monthly_dividend_forecast(year, seasonal=False, today=None)`:
    - Betaalmaanden = maanden met betalingen in het venster
      `datetime(today.year-1, today.month, 1)` t/m nu (uitgelijnd op de
      maandgrens, niet "365 dagen terug": anders valt een betaling van
      1-8 okt vorig jaar er net buiten).
    - Bedrag = per share x huidige qty x laatste FX.
    - Modus `median` (default): mediaan van de betalingen in het venster
      (dempt speciale dividenden).
    - Modus `seasonal`: SOM van de betalingen in de referentiemaand
      (meerdere betalingen in één maand tellen op); ontbreekt die -> mediaan.
      Referentiejaar: voor het huidige jaar `year-1`; voor volgend jaar de
      meest recente voorgaande voorkomst van die maand (dit jaar voor
      maanden vóór de huidige maand, anders vorig jaar). Speciale
      dividenden komen in seizoensmodus terug in hun maand (bewust).
    - Huidige maand telt mee en toont de INITIËLE verwachting; er wordt
      niets afgetrokken voor al ontvangen betalingen. De grafiek toont
      daarnaast de "Werkelijk"-balk met wat al is uitgekeerd.
    - Verleden jaren geven nullen; volgend jaar werkt (alle 12 maanden).
    - Crypto uitgesloten. `today` is een parameter zodat tests niet van de
      systeemdatum afhangen.
  - Onderaan het bestand staat een uitgecommentarieerde oude
    `compute_monthly_dividends`; dode code, kan weg.
- `web/charts/dividends.py`: `build_monthly_dividend_figure` — gegroepeerde
  balken "Werkelijk" + "Verwachting", hover met bijdragen per aandeel.
- API (`api/dividends.py`, prefix `/api/personal`): `dividend-calendar`,
  `dividend-annual-total`, `dividend-monthly`, `dividend-monthly/chart`,
  `dividend-monthly/forecast`, `dividend-estimate`, `POST sync-dividends`.
  `seasonal: bool` bestaat alleen op `.../chart` en `.../forecast`, NIET op
  `dividend-monthly` (`compute_monthly_dividends` kent die parameter niet).
- `web/dividends.html`: radiobuttons Gemiddeld/Seizoensgebonden (altijd één
  actief), jaar-dropdown t/m volgend jaar (standaard huidig jaar).
  **Plotly-gotcha:** na een jaarwissel kreeg de plot een hoogte van ~2 cm.
  Fix: `await Plotly.react(...)` gevolgd door
  `Plotly.Plots.resize('chart-monthly')`, plus vaste `height: 400` in de
  layout en CSS `#chart-monthly { height: 400px }`.
- `server.py`: route `/dividends` en link "Dividenden" in de nav-banner.

## Scripts (`my_portfolio/scripts/`)

| Script | Doel | Wijzigt data/library? |
|---|---|---|
| `apply_library_patches.py` | Patch toepassen / `--check` / `--revert` op geïnstalleerde library (vereist 0.5.13) | Library (site-packages) |
| `audit_library_changes.py` | Diff lokale library vs PyPI-wheel → `docs/LIBRARY_CHANGES.md` (`--out`, `--package-dir`, `--version`) | Nee |
| `diagnose_sector_data.py` | Read-only sector-dump | Nee |
| `reset_sector_data.py` | Wist sector/instrument-type-data (eenmalig) | DB |
| `fix_crypto_stocks.py` | Merge duplicate crypto-stocks, reset tickers/koersen (`--dry-run`) | DB |
| `diagnose_dividends.py` | Read-only dump van transacties, DividendPayment en yield voor een fonds op naam (`"<naam>" [--live]`; `--live` doet één Yahoo-call, schrijft niets) | Nee |

`audit_library_changes.py` noemt in zijn docstring een
`audit_core_imports.py` (import-oppervlak van `my_portfolio/` naar de
core) — aanwezigheid in de repo niet geverifieerd; ook de inhoud van
eventuele `docs/CORE_TOUCHPOINTS.md` / `CORE_IMPORTS.md` is niet bevestigd.

## Testen

`my_portfolio/tests/` — pytest, eigen tijdelijke SQLite-db per testrun
(`conftest.py` zet `DATABASE_URL` VÓÓR de eerste import van
`degiro_portfolio.database`; die bindt de engine bij import-tijd).
31 tests: 9 `test_sector_allocation.py`, 10 `test_watchlist.py`, 12
`test_dividends.py` (laatste 12 gedraaid en groen). Dividenden: 2x
`compute_monthly_dividends` + 10x forecast (kwartaalbetaler, huidige
maand, speciaal dividend, seizoensfallback, volgend jaar, meerdere
betalingen in één maand, crypto met `CRYPTO:`-ISIN, CRYPTOCURRENCY zonder
ISIN, echt ISIN wint van CRYPTOCURRENCY). `make_stock(isin=None)` vereist
dat `Stock.isin` nullable is; anders `isin=""`. Geen tests voor
`_verified_ticker`, `data/dividends.py`, scripts of patch-mechanisme.
Draaien: `python -m pytest my_portfolio/tests/ -v`

Client-side JS: geen browser-testrunner; Node.js beschikbaar — de
daadwerkelijk geserveerde `<script>`-inhoud wordt uit de live HTTP-response
gehaald en met gemockte `Plotly`/`document` tegen concrete scenario's
gedraaid.

## Omgeving

Windows / PowerShell, `.venv` in de projectroot
(`.venv\Lib\site-packages\degiro_portfolio`), Python 3.10+. `*.db` en
`*.xlsx` staan in `.gitignore` (persoonlijke data niet in repo). Desktop-
modus: `python -m my_portfolio.desktop --port 8000` (pywebview).

## Bekende, bewuste compromissen

- Geen DB-niveau FK op `StockMetadata.stock_id` / `WatchlistStock`
- `my_portfolio/desktop.py` importeert PRIVATE helpers uit
  `degiro_portfolio.desktop` (`run_desktop()` hardcodeert het modulepad) —
  kwetsbaar bij core-updates, geen upstream-fix voorgesteld
- ETF-sectordata onvolledig voor brede Europese indexfondsen;
  iShares/Vanguard-factsheet-provider overwogen, niet gebouwd
- Core-library is gepatcht en vastgepind op 0.5.13: upgraden vereist eerst
  een beoordeling van de patch, geen blind `pip install --upgrade`
- Dividend-EUR-waarde gebruikt de laatst bekende wisselkoers, niet de koers op de uitkeringsdatum
- `DividendPayment.payment_date` is de ex-datum, niet de betaaldatum
- Seizoensmodus bij volgend jaar: referentie is de meest recente voorgaande voorkomst van de maand, niet strikt `year-1`

## Werkwijze die goed werkt

1. Eerst analyseren (bestanden/functies/datastroom), dán coderen
2. Core-raakvlak: waarom nodig / welk probleem / effect op bestaande
   functionaliteit — en bij een echte core-patch: patchfile +
   `LIBRARY_CHANGES.md` bijwerken, hier documenteren
3. Elke wijziging ECHT testen (sandbox-server + curl, of Node voor JS) vóór
   aanbieden
4. Geen onnodige wijzigingen; extra bevindingen apart noemen onder
   "opmerking/later"
