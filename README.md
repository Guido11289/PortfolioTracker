# PortfolioTracker

Persoonlijke uitbreiding op de open-source
[`degiro_portfolio`](https://github.com/jdrumgoole/degiro_portfolio)-library:
sectoranalyse, watchlist en koershistorie-backfill. De extensie zit in het
losse `my_portfolio`-package; de library zelf wordt alleen gepatcht waar
`docs/LIBRARY_CHANGES.md` dat beschrijft (crypto-import, fractionele
hoeveelheden, performance-grafiek).

`my_portfolio/server.py` importeert de FastAPI-`app` uit
`degiro_portfolio.main` en verrijkt die at runtime met extra routes en
HTML-injecties. Architectuur en keuzes: zie `PROJECT_KNOWLEDGE.md`.

## Installatie (Windows / PowerShell)

Vereist: Python 3.10+ en Git.

### 1. Clonen

```powershell
git clone https://github.com/Guido11289/PortfolioTracker.git
cd PortfolioTracker
```

### 2. Virtual environment aanmaken en activeren

```powershell
python -m venv .venv
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& .\.venv\Scripts\Activate.ps1)
```

`Set-ExecutionPolicy -Scope Process` geldt alleen voor deze PowerShell-sessie,
dus er verandert niets permanent aan je systeem. Na activeren staat
`(.venv)` voor je prompt. Bij een nieuwe terminal opnieuw activeren.

### 3. Dependencies installeren

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`degiro_portfolio` staat vastgepind op **0.5.13**: de patches in stap 4 zijn
daartegen gemaakt. Niet upgraden zonder de patches opnieuw te beoordelen.

### 4. Library-patches toepassen

De geïnstalleerde library moet op een aantal plekken aangepast worden.
Alles staat als diff in [`docs/LIBRARY_CHANGES.md`](docs/LIBRARY_CHANGES.md).
Doorloop die file en pas de wijzigingen handmatig toe in:

```
.venv\Lib\site-packages\degiro_portfolio\
```

| Bestand | Wijziging |
|---|---|
| `config.py` | 17-kolommen-export, `_fix_crypto_rows` (crypto zonder ISIN/quantity) |
| `database.py` | `Transaction.quantity` van `Integer` naar `Float` |
| `import_data.py` | `int(quantity)` → `float(quantity)` |
| `fetch_prices.py` | startdatum 10 dagen vóór eerste transactie |
| `main.py` | `int(qty)` weg, `timedelta`-import, 10 dagen extra prijshistorie |
| `static\index.html` | performance-grafiek + markers voor nieuwe investeringen |
| `ticker_resolver.py` | `resolve_crypto_ticker` + crypto-pad in `get_ticker_for_stock` |

Controle dat de installatie overeenkomt met `LIBRARY_CHANGES.md` (vereist
internet; exit code 1 is hier normaal, want er *zijn* verschillen):

```powershell
python -m my_portfolio.scripts.audit_library_changes --out $env:TEMP\check.md
```

Vergelijk `$env:TEMP\check.md` met `docs/LIBRARY_CHANGES.md`: die moeten
inhoudelijk gelijk zijn.

> Patches verdwijnen bij `pip install --upgrade degiro_portfolio` of een
> verse venv. Na elke herinstallatie stap 4 herhalen.

### 5. Starten

```powershell
python -m uvicorn my_portfolio.server:app --host 127.0.0.1 --port 8000
```

Open daarna <http://127.0.0.1:8000/>.

Niet `python -m degiro_portfolio` gebruiken: dat start de kale core-app
zonder de extensie.

| URL | Pagina |
|---|---|
| `/` | Core-dashboard (+ nav-banner, backfill-knop, chart-range-fix) |
| `/personal` | Sectorweging (stocks / ETF's / totaal) |
| `/watchlist` | Watchlist met fundamentals- en koersfilters |
| `/docs` | Swagger UI (incl. `/api/personal/*`) |

## Eerste gebruik

1. DEGIRO-transactie-export importeren via het core-dashboard (`/`).
2. Op `/personal`: **Sync sector-data (Yahoo)**. Duurt even door de
   Yahoo-rate-limiter (~3 s per aandeel).
3. Optioneel op `/`: **Backfill historische koersen (5 jaar)** onder de
   Stock Price-grafiek.

## Database-locatie

De library leest `DATABASE_URL` (niet `DEGIRO_PORTFOLIO_DB`, die staat wel in
`config.py` maar wordt nergens gebruikt). Optioneel, voor het starten:

```powershell
$env:DATABASE_URL = "sqlite:///C:/pad/naar/portfolio.db"
```

`*.db` staat in `.gitignore`; persoonlijke data komt niet in de repo.

## Tests

```powershell
python -m pytest my_portfolio/tests/ -v
```

Gebruikt een tijdelijke SQLite-db per run; je echte data blijft onaangeroerd.

## Desktop-modus (optioneel)

```powershell
python -m my_portfolio.desktop --port 8000
```

Gebruikt `pywebview` (wordt door `degiro_portfolio` meegeïnstalleerd).
Importeert private helpers uit `degiro_portfolio.desktop`; kwetsbaar bij
library-updates.
