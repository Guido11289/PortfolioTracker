# Lokale wijzigingen t.o.v. de PyPI-release

Vergelijking van `C:\Speeltuin_Guido\tracker\.venv\Lib\site-packages\degiro_portfolio` tegen `degiro_portfolio==0.5.13` zoals gepubliceerd op PyPI. Gegenereerd door `python -m my_portfolio.scripts.audit_library_changes`.

⚠️ Dit betekent dat de geïnstalleerde library lokaal is aangepast — in strijd met het architectuurprincipe dat de core-library nooit wordt gewijzigd. Elke wijziging hieronder verdwijnt bij de volgende `pip install --upgrade` en moet dus ofwel teruggeport worden naar `my_portfolio/`, ofwel bewust losgelaten worden.

## Gewijzigde bestanden (7)

### `config.py`

```diff
--- pypi/config.py
+++ lokaal/config.py
@@ -223,16 +223,60 @@
 
         if ncols == cls.DEGIRO_EXPECTED_COLUMN_COUNT:
             df.columns = cls.DEGIRO_COLUMN_ORDER
-            return df
-
-        if ncols == 18:
-            return cls._normalize_18col(df)
+            return cls._fix_crypto_rows(df)
+
+        if ncols in (17, 18):
+            # 17 kolommen: nieuwere DEGIRO-export zonder de trailing lege
+            # 18e kolom. DEGIRO_18COL_POSITIONS gebruikt toch nooit positie
+            # 17, dus dezelfde positionele selectie werkt voor beide.
+            return cls._fix_crypto_rows(cls._normalize_18col(df))
 
         raise ValueError(
-            f"Expected {cls.DEGIRO_EXPECTED_COLUMN_COUNT} or 18 columns in "
-            f"DEGIRO export, got {ncols}.  "
-            f"Columns found: {list(df.columns)}"
-        )
+            f"Expected {cls.DEGIRO_EXPECTED_COLUMN_COUNT}, 17 or 18 columns "
+            f"in DEGIRO export, got {ncols}.  "
+             f"Columns found: {list(df.columns)}"
+         )
+ 
+    @classmethod
+    def _fix_crypto_rows(cls, df):
+        """Herstelt DEGIRO's crypto-eigenaardigheid (BITCOIN, NEAR PROTOCOL, ...).
+
+        Voor crypto-trades laat DEGIRO zowel ISIN als Quantity leeg. Price
+        is wel gewoon de prijs per eenheid (bv. 70098,50 EUR/BTC) — alleen
+        Quantity ontbreekt. Zonder fix crasht de import (int(NaN)) en
+        zouden verschillende crypto's met isin="" op dezelfde Stock-rij
+        botsen.
+        """
+        import pandas as pd
+
+        isin_col = cls.DEGIRO_COLUMNS['isin']
+        qty_col = cls.DEGIRO_COLUMNS['quantity']
+        price_col = cls.DEGIRO_COLUMNS['price']
+        value_col = cls.DEGIRO_COLUMNS['value_eur']
+        product_col = cls.DEGIRO_COLUMNS['product']
+
+        isin_blank = df[isin_col].isna() | (df[isin_col].astype(str).str.strip() == "")
+        qty_blank = df[qty_col].isna() | (df[qty_col].astype(str).str.strip() == "")
+        is_crypto = isin_blank & qty_blank
+
+        if is_crypto.any():
+            price = pd.to_numeric(df.loc[is_crypto, price_col], errors="coerce")
+            value_eur = pd.to_numeric(df.loc[is_crypto, value_col], errors="coerce")
+            qty_magnitude = (value_eur.abs() / price).where(price != 0, 0.0)
+
+            # Teken van de hoeveelheid volgt de bestaande conventie voor
+            # gewone aandelen: buy (negatieve Value EUR) -> positieve
+            # quantity, sell (positieve Value EUR) -> negatieve quantity.
+            df.loc[is_crypto, qty_col] = qty_magnitude.where(value_eur < 0, -qty_magnitude)
+
+            # Price stond al goed (prijs per eenheid) — niet aanraken.
+
+            df.loc[is_crypto, isin_col] = (
+                "CRYPTO:" + df.loc[is_crypto, product_col].astype(str).str.strip().str.upper()
+            )
+
+        return df
+
 
     @classmethod
     def _normalize_18col(cls, df):
```

### `database.py`

```diff
--- pypi/database.py
+++ lokaal/database.py
@@ -51,12 +51,11 @@
 class Transaction(Base):
     """Stock transaction history."""
     __tablename__ = "transactions"
-
     id = Column(Integer, primary_key=True, index=True)
     stock_id = Column(Integer, ForeignKey("stocks.id"))
     date = Column(DateTime, index=True)
     time = Column(String)
-    quantity = Column(Integer)
+    quantity = Column(Float)  # Float i.p.v. Integer: crypto-hoeveelheden zijn fractioneel
     price = Column(Float)  # Price in original currency
     currency = Column(String)  # Currency for the price (EUR, USD, SEK, etc.)
     value_eur = Column(Float)
```

### `fetch_prices.py`

```diff
--- pypi/fetch_prices.py
+++ lokaal/fetch_prices.py
@@ -105,7 +105,10 @@
             stock_id=stock.id
         ).scalar()
         if earliest_trans:
-            start_date = earliest_trans.date()
+            # Fetch additional historical data before the first transaction.
+            # 10 calendar days gives us roughly 5 trading days, accounting
+            # for weekends and market holidays.
+            start_date = earliest_trans.date() - timedelta(days=10)
         else:
             start_date = datetime.now().date() - timedelta(days=365)
 
```

### `import_data.py`

```diff
--- pypi/import_data.py
+++ lokaal/import_data.py
@@ -155,7 +155,7 @@
                 stock_id=stock.id,
                 date=trans_date,
                 time=row[get_column('time')],
-                quantity=int(row[get_column('quantity')]),
+                quantity=float(row[get_column('quantity')]),
                 price=float(row[get_column('price')]),
                 currency=transaction_currency,  # Store original currency
                 value_eur=float(row[get_column('value_eur')]),
```

### `main.py`

```diff
--- pypi/main.py
+++ lokaal/main.py
@@ -19,7 +19,7 @@
 from .database import get_db, Stock, Transaction, StockPrice, Index, IndexPrice, ExchangeRate, init_db
 from .config import Config, get_column
 from .import_data import parse_date
-from .fetch_prices import fetch_stock_prices
+from .fetch_prices import fetch_stock_prices, timedelta
 from .price_fetchers import get_price_fetcher, yahoo_rate_limiter
 
 logger = logging.getLogger(__name__)
@@ -203,7 +203,7 @@
         return {"holdings": []}
 
     # Filter to stocks with positive holdings
-    active_holdings = [(stock, int(qty), count) for stock, qty, count in holdings_data if qty and qty > 0]
+    active_holdings = [(stock, qty, count) for stock, qty, count in holdings_data if qty and qty > 0]
 
     if not active_holdings:
         return {"holdings": []}
@@ -760,7 +760,7 @@
         }
 
     stock_ids = [stock.id for stock, _ in holdings_query]
-    shares_by_id = {stock.id: int(qty) for stock, qty in holdings_query}
+    shares_by_id = {stock.id: qty for stock, qty in holdings_query}
 
     # Compute net invested per stock: sum(|total_eur|) for buys - sum(|total_eur|) for sells
     total_net_invested = 0.0
@@ -808,7 +808,7 @@
             rate = exchange_rates_map.get(currency, _get_fallback_rate(currency))
             scaled = price_record.close * price_scales.get(stock.id, 1.0)
             price_eur = scaled * rate
-            current_value += int(qty) * price_eur
+            current_value += qty * price_eur
 
     gain_loss = current_value - total_net_invested
     gain_loss_percent = (gain_loss / total_net_invested * 100) if total_net_invested > 0 else 0.0
@@ -893,7 +893,7 @@
             "name": stock.name,
             "symbol": stock.symbol,
             "currency": stock.currency,
-            "shares": int(total_qty),
+            "shares": total_qty,
             "performance": performance
         })
 
@@ -941,7 +941,7 @@
 
     # Get all unique dates from price history after first transaction
     price_dates = db.query(StockPrice.date).filter(
-        StockPrice.date >= first_trans_date
+        StockPrice.date >= first_trans_date - timedelta(days=10)
     ).distinct().order_by(StockPrice.date).all()
 
     if not price_dates:
@@ -957,7 +957,7 @@
 
     # Pre-fetch ALL prices into memory - keyed by (stock_id, date)
     all_prices = db.query(StockPrice).filter(
-        StockPrice.date >= first_trans_date
+        StockPrice.date >= first_trans_date - timedelta(days=10)
     ).all()
 
     # Build price lookup: for each stock, sorted list of (date, price, currency)
@@ -1151,7 +1151,7 @@
                 existing_trans = db.query(Transaction).filter(
                     Transaction.stock_id == stock.id,
                     Transaction.date == trans_date,
-                    Transaction.quantity == int(row[get_column('quantity')]),
+                    Transaction.quantity == float(row[get_column('quantity')]),
                     Transaction.price == float(row[get_column('price')])
                 ).first()
 
@@ -1160,7 +1160,7 @@
                         stock_id=stock.id,
                         date=trans_date,
                         time=str(row[get_column('time')]),
-                        quantity=int(row[get_column('quantity')]),
+                        quantity=float(row[get_column('quantity')]),
                         price=float(row[get_column('price')]),
                         currency=row[get_column('currency')],
                         value_eur=float(row[get_column('value_eur')]),
```

### `static\index.html`

```diff
--- pypi/static\index.html
+++ lokaal/static\index.html
@@ -338,9 +338,14 @@
             height: 350px;
         }
 
-        #portfolio-valuation-chart {
-            width: 100%;
-            height: 400px;
+        #portfolio-valuation-chart { 
+            width: 100%; 
+            height: 400px; 
+        }
+
+        #portfolio-performance-chart { 
+            width: 100%; 
+            height: 180px; 
         }
 
         #portfolio-chart-section {
@@ -759,9 +764,22 @@
         </div>
 
         <!-- Portfolio Valuation Chart -->
-        <div id="portfolio-chart-section" class="chart-container" style="display: none; margin-bottom: 30px;">
-            <div class="chart-title">Portfolio Total Value Over Time</div>
+        <div id="portfolio-chart-section"
+            class="chart-container"
+            style="display: none; margin-bottom: 30px;">
+
+            <div class="chart-title">
+                Portfolio Total Value Over Time
+            </div>
+
             <div id="portfolio-valuation-chart"></div>
+
+            <div id="portfolio-performance-chart"
+                style="width: 100%; height: 180px; margin-top: 10px;">
+                Performance
+            </div>
+            <div id="portfolio-performance-chart"></div>
+
         </div>
 
         <div id="holdings-container" style="display: none;">
@@ -1007,7 +1025,51 @@
                 // Show the chart section
                 document.getElementById('portfolio-chart-section').style.display = 'block';
 
-                // Create traces
+                // ============================================================
+                // 1. CALCULATE PERFORMANCE
+                // ============================================================
+
+                const performancePercent = data.values.map((value, i) => {
+                    const invested = data.invested[i];
+
+                    if (!invested || invested === 0) {
+                        return null;
+                    }
+
+                    return ((value - invested) / invested) * 100;
+                });
+
+                // ============================================================
+                // 2. FIND NEW INVESTMENT EVENTS
+                // ============================================================
+
+                const investmentEvents = [];
+
+                for (let i = 1; i < data.dates.length; i++) {
+                    const previousInvested = data.invested[i - 1];
+                    const currentInvested = data.invested[i];
+
+                    if (
+                        previousInvested != null &&
+                        currentInvested != null &&
+                        currentInvested > previousInvested
+                    ) {
+                        const addedAmount = currentInvested - previousInvested;
+
+                        investmentEvents.push({
+                            date: data.dates[i],
+                            performance: performancePercent[i],
+                            added: addedAmount,
+                            previous: previousInvested,
+                            current: currentInvested
+                        });
+                    }
+                }
+
+                // ============================================================
+                // 3. TOP CHART - PORTFOLIO VALUE
+                // ============================================================
+
                 const portfolioTrace = {
                     x: data.dates,
                     y: data.values,
@@ -1019,7 +1081,8 @@
                     },
                     fill: 'tonexty',
                     fillcolor: 'rgba(102, 126, 234, 0.1)',
-                    hovertemplate: '<b>Portfolio Value</b><br>€%{y:,.2f}<br>%{x}<extra></extra>'
+                    hovertemplate:
+                        '<b>Portfolio Value</b><br>€%{y:,.2f}<br>%{x}<extra></extra>'
                 };
 
                 const investedTrace = {
@@ -1032,12 +1095,39 @@
                         width: 2,
                         dash: 'dash'
                     },
-                    hovertemplate: '<b>Net Invested</b><br>€%{y:,.2f}<br>%{x}<extra></extra>'
+                    hovertemplate:
+                        '<b>Net Invested</b><br>€%{y:,.2f}<br>%{x}<extra></extra>'
                 };
 
-                // Get the most recent date and value
+                // Red markers on the Net Invested line
+                const investmentValueEventTrace = {
+                    x: investmentEvents.map(event => event.date),
+                    y: investmentEvents.map(event => event.current),
+                    mode: 'markers',
+                    name: 'New Investment',
+                    marker: {
+                        color: '#e53e3e',
+                        size: 10,
+                        symbol: 'triangle-up',
+                        line: {
+                            color: 'white',
+                            width: 1
+                        }
+                    },
+                    customdata: investmentEvents.map(event => [
+                        event.added,
+                        event.previous,
+                        event.current
+                    ]),
+                    hovertemplate:
+                        '<b>💰 New Investment</b>' +
+                        '<br>Added: <b>€%{customdata[0]:,.2f}</b>' +
+                        '<br>Net invested: €%{customdata[1]:,.2f} → €%{customdata[2]:,.2f}' +
+                        '<br>%{x}' +
+                        '<extra></extra>'
+                };
+
                 const lastDate = data.dates[data.dates.length - 1];
-                const lastValue = data.values[data.values.length - 1];
 
                 const layout = {
                     xaxis: {
@@ -1045,20 +1135,24 @@
                         type: 'date',
                         gridcolor: '#e2e8f0'
                     },
+
                     yaxis: {
                         title: 'Value (EUR)',
                         gridcolor: '#e2e8f0',
                         tickformat: ',.0f',
                         tickprefix: '€'
                     },
+
                     hovermode: 'x unified',
                     showlegend: true,
+
                     legend: {
                         x: 0,
                         y: 1.15,
                         orientation: 'h',
                         bgcolor: 'rgba(255, 255, 255, 0.9)'
                     },
+
                     annotations: [{
                         x: 1,
                         y: 1.08,
@@ -1079,9 +1173,15 @@
                             family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
                         }
                     }],
+
                     plot_bgcolor: '#f7fafc',
                     paper_bgcolor: 'white',
-                    margin: { t: 10, b: 40 },
+
+                    margin: {
+                        t: 10,
+                        b: 40
+                    },
+
                     font: {
                         family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
                     }
@@ -1094,10 +1194,149 @@
                     modeBarButtonsToRemove: ['lasso2d', 'select2d']
                 };
 
-                Plotly.newPlot('portfolio-valuation-chart', [investedTrace, portfolioTrace], layout, config);
+                // Render TOP chart
+                Plotly.newPlot(
+                    'portfolio-valuation-chart',
+                    [
+                        investedTrace,
+                        portfolioTrace,
+                        investmentValueEventTrace
+                    ],
+                    layout,
+                    config
+                );
+
+                // ============================================================
+                // 4. BOTTOM CHART - PERFORMANCE %
+                // ============================================================
+
+                const performanceTrace = {
+                    x: data.dates,
+                    y: performancePercent,
+                    mode: 'lines',
+                    name: 'Performance',
+                    line: {
+                        color: '#667eea',
+                        width: 2
+                    },
+                    hovertemplate:
+                        '<b>Performance</b><br>%{y:.2f}%<br>%{x}<extra></extra>'
+                };
+
+                // Red markers on performance chart
+                const investmentEventTrace = {
+                    x: investmentEvents.map(event => event.date),
+                    y: investmentEvents.map(event => event.performance),
+                    mode: 'markers',
+                    name: 'New Investment',
+                    marker: {
+                        color: '#e53e3e',
+                        size: 10,
+                        symbol: 'triangle-up',
+                        line: {
+                            color: 'white',
+                            width: 1
+                        }
+                    },
+                    customdata: investmentEvents.map(event => [
+                        event.added,
+                        event.previous,
+                        event.current
+                    ]),
+                    hovertemplate:
+                        '<b>💰 New Investment</b>' +
+                        '<br>Added: <b>€%{customdata[0]:,.2f}</b>' +
+                        '<br>Net invested: €%{customdata[1]:,.2f} → €%{customdata[2]:,.2f}' +
+                        '<br>Performance: <b>%{y:.2f}%</b>' +
+                        '<br>%{x}' +
+                        '<extra></extra>'
+                };
+
+                // ============================================================
+                // 5. SYMMETRIC Y-AXIS AROUND 0%
+                // ============================================================
+
+                const validPerformance = performancePercent.filter(
+                    value => value !== null && Number.isFinite(value)
+                );
+
+                const maxPerformance = validPerformance.length > 0
+                    ? Math.max(...validPerformance.map(value => Math.abs(value)))
+                    : 10;
+
+                // 10% padding around largest absolute value
+                const performanceAxisLimit = Math.max(maxPerformance * 1.1, 1);
+
+                const performanceLayout = {
+                    xaxis: {
+                        title: 'Date',
+                        type: 'date',
+                        gridcolor: '#e2e8f0'
+                    },
+
+                    yaxis: {
+                        title: 'Performance',
+                        ticksuffix: '%',
+                        tickformat: '.1f',
+                        range: [
+                            -performanceAxisLimit,
+                            performanceAxisLimit
+                        ],
+                        zeroline: false,
+                        gridcolor: '#e2e8f0'
+                    },
+
+                    // Explicit 0% line
+                    shapes: [{
+                        type: 'line',
+                        x0: 0,
+                        x1: 1,
+                        xref: 'paper',
+                        y0: 0,
+                        y1: 0,
+                        yref: 'y',
+                        line: {
+                            color: '#718096',
+                            width: 2,
+                            dash: 'dash'
+                        }
+                    }],
+
+                    hovermode: 'x unified',
+                    showlegend: false,
+
+                    plot_bgcolor: '#f7fafc',
+                    paper_bgcolor: 'white',
+
+                    margin: {
+                        t: 10,
+                        b: 40,
+                        l: 60,
+                        r: 60
+                    },
+
+                    font: {
+                        family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
+                    }
+                };
+
+                // Render BOTTOM performance chart
+                Plotly.newPlot(
+                    'portfolio-performance-chart',
+                    [
+                        performanceTrace,
+                        investmentEventTrace
+                    ],
+                    performanceLayout,
+                    config
+                );
 
             } catch (error) {
-                console.error('Failed to load portfolio valuation chart:', error);
+                console.error(
+                    'Failed to load portfolio valuation chart:',
+                    error
+                );
+
                 // Check if server went offline
                 await checkServerStatus();
             }
```

### `ticker_resolver.py`

```diff
--- pypi/ticker_resolver.py
+++ lokaal/ticker_resolver.py
@@ -112,6 +112,51 @@
     # US: no suffix — Yahoo uses bare ticker (AAPL, MSFT). Omitted intentionally.
 }
 
+ 
+
+def resolve_crypto_ticker(product_name: str, currency: Optional[str] = None) -> Optional[str]:
+    """Resolve a Yahoo Finance ticker for a crypto product (BITCOIN, NEAR PROTOCOL, ...).
+
+    Los van resolve_ticker_from_isin/_from_name: die twee filteren
+    Yahoo-searchresultaten op quoteType EQUITY/ETF/MUTUALFUND (zie
+    _pick_best_search_match), waardoor een zoekopdracht op "BITCOIN" een
+    Bitcoin-ETF (bv. IBIT) oplevert i.p.v. de coin zelf. Hier filteren we
+    juist op quoteType == CRYPTOCURRENCY.
+
+    De Yahoo search zelf levert voor de gewenste quote-currency (EUR) lang
+    niet altijd een kandidaat op (search lijkt vaak alleen "<ROOT>-USD" te
+    tonen, ook als "<ROOT>-EUR" wél gewoon bestaat als los quote). Daarom:
+    root-symbool uit het eerste treffer halen en zelf "<ROOT>-<currency>"
+    verifiëren i.p.v. te vertrouwen op wat de search toevallig teruggeeft.
+    """
+    quote_currency = currency if currency in ("EUR", "USD") else "USD"
+    try:
+        result = yf.Search(product_name)
+        crypto_quotes = [q for q in result.quotes if q.get("quoteType") == "CRYPTOCURRENCY"]
+    except Exception as e:
+        logger.debug(f"Yahoo crypto search for '{product_name}' failed: {e}")
+        return None
+
+    if not crypto_quotes:
+        return None
+
+    fallback_symbol = crypto_quotes[0].get("symbol", "")
+    root = fallback_symbol.split("-")[0] if "-" in fallback_symbol else fallback_symbol
+
+    if quote_currency != "USD" and root:
+        candidate = f"{root}-{quote_currency}"
+        if _verify_ticker(candidate):
+            return candidate
+        logger.debug(f"{candidate} niet beschikbaar op Yahoo, val terug op {fallback_symbol}")
+
+    for q in crypto_quotes:
+        symbol = q.get("symbol", "")
+        if symbol.endswith(f"-{quote_currency}"):
+            return symbol
+
+    # Geen match voor de gewenste quote-currency (bv. geen "-EUR" notering
+    # voor deze coin) -> eerste crypto-resultaat, meestal "-USD".
+    return crypto_quotes[0].get("symbol")
 
 def _pick_best_search_match(
     quotes: List[dict],
@@ -341,6 +386,17 @@
     Returns:
         Yahoo Finance ticker symbol if found, None otherwise
     """
+    # Onze eigen crypto-rijen krijgen een synthetische "CRYPTO:<naam>" ISIN
+    # (zie Config._fix_crypto_rows) — dat is geen echte ISIN, dus sla de
+    # normale ISIN/naam-resolutie over en zoek direct op quoteType
+    # CRYPTOCURRENCY. Anders resolved "BITCOIN" naar een Bitcoin-ETF i.p.v.
+    # de coin zelf (zie resolve_crypto_ticker).
+    if stock_isin and stock_isin.startswith("CRYPTO:"):
+        ticker = resolve_crypto_ticker(stock_name, currency)
+        if ticker:
+            return ticker
+        logger.warning(f"Could not resolve crypto ticker for {stock_name}, val terug op normale resolutie")
+
     # Try ISIN resolution first
     ticker = resolve_ticker_from_isin(stock_isin, currency)
     if ticker:
```
