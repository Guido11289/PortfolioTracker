"""Entrypoint voor de personal extensie.

Start dit i.p.v. `degiro_portfolio.main:app`. Dit bestand:
  1. importeert de ongewijzigde core FastAPI `app`;
  2. hangt de personal-routers eronder op /api/personal/*;
  3. voegt één extra route toe (/personal) die de personal-dashboardpagina serveert;
  4. vervangt de "/"-route zodat er een link naar /personal in staat.

Geen enkel bestand in de geïnstalleerde degiro_portfolio-library wordt
aangepast — punt 4 leest het originele index.html-bestand van disk (dat
blijft ongewijzigd) en injecteert alleen bij het serveren een kleine
nav-banner in de response. `app` hieronder IS het core-object.
"""
import os

from fastapi.responses import FileResponse, HTMLResponse

from degiro_portfolio.main import app as app  # het echte, ongewijzigde core-object
from degiro_portfolio.database import init_db

from .database import init_personal_db
from .api import system as system_api
from .api import sector as sector_api
from .api import watchlist as watchlist_api
from .api import prices as prices_api

# --- Personal API mounten -------------------------------------------------
app.include_router(system_api.router, prefix="/api/personal", tags=["personal"])
app.include_router(sector_api.router, prefix="/api/personal", tags=["personal", "sector"])
app.include_router(watchlist_api.router, prefix="/api/personal", tags=["personal", "watchlist"])
app.include_router(prices_api.router, prefix="/api/personal", tags=["personal", "prices"])

# --- Personal frontend-pagina toevoegen (naast, niet i.p.v. core index.html) ---
_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_CORE_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "degiro_portfolio", "static")
# Robuustere manier om de core static-map te vinden, ongeacht install-locatie:
import degiro_portfolio.main as _core_main
_CORE_STATIC_DIR = os.path.join(os.path.dirname(_core_main.__file__), "static")


@app.get("/personal")
def personal_dashboard():
    return FileResponse(os.path.join(_WEB_DIR, "personal.html"))


@app.get("/watchlist")
def watchlist_dashboard():
    return FileResponse(os.path.join(_WEB_DIR, "watchlist.html"))


# --- "/" overschrijven: nav-banner + backfill-knop direct onder de
#     "Stock Price"-grafiek zelf (i.p.v. op een aparte pagina) -----------
# Waarom dit laatste stuk (backfill-knop) hier hoort en niet op /personal:
#   het effect ervan (meer historie op de Stock Price-grafiek) is alleen
#   zichtbaar op déze pagina — een knop op een andere pagina die iets
#   hiér verandert is verwarrende UX, terecht opgemerkt.
# Wat lost het op: knop en effect op dezelfde plek, geen paginawissel nodig.
# Effect op bestaande functionaliteit: geen. We forken het bestand NIET —
#   we lezen het bij elke request nog steeds vers van disk (dus als de
#   core-library ooit update, krijg je die update automatisch mee) en
#   injecteren alleen 2 kleine blokken op vaste, unieke ankerpunten. Een
#   volledige fork zou dat automatisch-meekrijgen van core-verbeteringen
#   permanent verliezen — dat is bewust NIET gedaan, zie ook het antwoord
#   in de chat hierover.
_original_root_route = next(
    (r for r in app.router.routes if getattr(r, "path", None) == "/" and "GET" in getattr(r, "methods", set())),
    None,
)
if _original_root_route is not None:
    app.router.routes.remove(_original_root_route)

_PERSONAL_BANNER = (
    '<div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);'
    'color:white;padding:10px 20px;font-family:-apple-system,BlinkMacSystemFont,'
    '\'Segoe UI\',Roboto,sans-serif;font-size:14px;text-align:right;'
    'box-shadow:0 2px 8px rgba(0,0,0,0.15);">'
    '<a href="/personal" style="color:white;font-weight:600;text-decoration:none;">Sectorweging</a>'
    '&nbsp;&nbsp;·&nbsp;&nbsp;'
    '<a href="/watchlist" style="color:white;font-weight:600;text-decoration:none;">Watchlist</a>'
    "</div>"
)

# Wordt na <div id="chart"></div> geplakt — dus direct onder de Stock
# Price-grafiek van het geselecteerde aandeel.
_BACKFILL_BUTTON = (
    '<div style="margin:10px 0 20px 0;">'
    '<button onclick="personalBackfillPrices()" style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);'
    'color:white;border:none;padding:8px 16px;border-radius:6px;font-size:0.85em;font-weight:600;'
    'cursor:pointer;box-shadow:0 4px 12px rgba(102,126,234,0.3);">'
    "Backfill historische koersen (5 jaar)</button>"
    '<span id="personal-backfill-status" style="margin-left:10px;color:#718096;font-size:0.85em;"></span>'
    "</div>"
)

# Wordt vóór </body> geplakt. Twee losse doelen:
#  1) personalBackfillPrices() — de backfill-knop-handler.
#  2) Standaard-view op de eerste-aankoopdatum voor de grafieken die
#     historie tonen ('chart' = Stock Price, 'index-chart' = Performance
#     vs. Market Indices), zonder de data zelf te beperken (handmatig
#     uitzoomen blijft mogelijk).
#
# Herziene aanpak t.o.v. de vorige versie — twee fouten die uit een eerste
# poging bleken:
#   a) De eerste versie las de aankoopdatum uit de al-gefilterde Plotly
#      'Buy'-trace (data.transactions.filter(t => t.currency === currency)
#      in de core's renderChart()). Bij een currency-mismatch tussen de
#      DEGIRO-transactie en de gedetecteerde beurs-currency (blijkbaar het
#      geval bij de S&P-ETF) is die trace LEEG, en deed de override dus
#      niets. Fix: renderChart() zelf wrappen — die functie krijgt de
#      ONGEFILTERDE data.transactions binnen, vóór die currency-filter.
#   b) yaxis.autorange:true bleek in de praktijk NIET automatisch te
#      beperken tot het zichtbare x-bereik (bevestigd door de gebruiker:
#      y-as toonde nog steeds 5 jaar aan spreiding). Fix: y-range zelf
#      berekenen uit de daadwerkelijke trace-datapunten binnen het
#      gekozen x-venster, i.p.v. op Plotly's autorange te vertrouwen.
#   c) De standaard-view werd ook opnieuw afgedwongen bij elke automatische
#      refresh (de core ververst elke minuut), waardoor een handmatige
#      zoom steeds na hooguit een minuut weer verdween. Fix: alleen
#      toepassen bij een nieuwe aandeel-selectie, niet bij een redraw van
#      hetzelfde aandeel — zie de wrapper hieronder voor het volledige
#      onderscheid.
_BACKFILL_SCRIPT = """
<script>
async function personalBackfillPrices() {
    if (typeof selectedStockId === 'undefined' || !selectedStockId) {
        alert('Selecteer eerst een aandeel.');
        return;
    }
    const status = document.getElementById('personal-backfill-status');
    status.textContent = 'bezig... (kan een paar minuten duren)';
    try {
        const res = await fetch(`/api/personal/backfill-prices?years_back=5&stock_id=${selectedStockId}`, { method: 'POST' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        status.textContent = `${data.total_added} nieuwe koersrecords toegevoegd (vanaf ${data.start_date})`;
        if (typeof loadStockChart === 'function') {
            loadStockChart(selectedStockId);
        }
    } catch (err) {
        status.textContent = '';
        alert('Backfill mislukt: ' + err.message);
    }
}

(function() {
    if (typeof Plotly === 'undefined') return;

    let personalXRange = null;  // [firstBuyDate, lastDate], gezet door de renderChart-wrapper

    function personalYRangeInWindow(traces, xMin, xMax) {
        let lo = Infinity, hi = -Infinity;
        traces.forEach(t => {
            if (!t.x) return;
            t.x.forEach((x, i) => {
                if (x < xMin || x > xMax) return;
                const candidates = [];
                if (t.low !== undefined && t.high !== undefined) {
                    if (t.low[i] != null) candidates.push(t.low[i]);
                    if (t.high[i] != null) candidates.push(t.high[i]);
                } else if (t.y !== undefined && t.y[i] != null) {
                    candidates.push(t.y[i]);
                }
                candidates.forEach(v => {
                    if (typeof v !== 'number' || isNaN(v)) return;
                    if (v < lo) lo = v;
                    if (v > hi) hi = v;
                });
            });
        });
        if (lo === Infinity || hi === -Infinity) return null;
        const pad = (hi - lo) * 0.05 || Math.abs(hi) * 0.05 || 1;
        return [lo - pad, hi + pad];
    }

    // --- renderChart() wrappen: leest de ONGEFILTERDE transacties -------
    if (typeof renderChart === 'function') {
        const originalRenderChart = renderChart;
        renderChart = function(data) {
            try {
                const buyDates = (data.transactions || [])
                    .filter(t => t.transaction_type === 'buy')
                    .map(t => t.date)
                    .filter(Boolean);
                const priceDates = (data.prices || []).map(p => p.date).filter(Boolean);
                if (buyDates.length && priceDates.length) {
                    const firstBuy = buyDates.reduce((min, d) => (d < min ? d : min), buyDates[0]);
                    const lastPrice = priceDates[priceDates.length - 1];
                    personalXRange = [firstBuy, lastPrice];
                } else {
                    personalXRange = null;
                }
            } catch (e) {
                console.warn('personal xRange-berekening mislukt, val terug op standaardgedrag', e);
                personalXRange = null;
            }
            return originalRenderChart.call(this, data);
        };
    }

    // --- Plotly.newPlot wrappen: past x- én y-range toe op de charts die
    //     historie tonen ('chart', 'index-chart') --------------------------
    // Belangrijk: de core ververst deze grafieken automatisch elke minuut
    // (chartRefreshInterval in loadStockChart()), en Plotly.newPlot tekent
    // de plot dan VOLLEDIG opnieuw — dat wist altijd de huidige zoom/pan,
    // ook zonder onze wrapper (bekend Plotly-gedrag; Plotly.react zou dit
    // niet doen, maar de core gebruikt newPlot). Onze wrapper maakte dit
    // eerder erger door bij ELKE redraw opnieuw de standaard-view af te
    // dwingen. Fix: alleen de standaard-view toepassen bij een NIEUWE
    // aandeel-selectie; bij een redraw van hetzelfde aandeel (refresh)
    // lezen we het huidige zichtbare bereik terug uit de bestaande
    // DOM-node (Plotly houdt dat live bij in `element.layout`) en zetten
    // dat expliciet terug, zodat een handmatige zoom de refresh overleeft.
    let personalRenderedStockId = null;

    const originalNewPlot = Plotly.newPlot;
    Plotly.newPlot = function(el, data, layout, config) {
        try {
            const elId = typeof el === 'string' ? el : (el && el.id);
            if ((elId === 'chart' || elId === 'index-chart') && Array.isArray(data)) {
                const currentStockId = (typeof selectedStockId !== 'undefined') ? selectedStockId : null;
                const isNewStock = personalRenderedStockId !== currentStockId;

                if (isNewStock && personalXRange) {
                    const [xMin, xMax] = personalXRange;
                    const yRange = personalYRangeInWindow(data, xMin, xMax);
                    const newLayout = Object.assign({}, layout, {
                        xaxis: Object.assign({}, layout.xaxis, { range: [xMin, xMax], autorange: false }),
                    });
                    if (yRange) {
                        newLayout.yaxis = Object.assign({}, layout.yaxis, { range: yRange, autorange: false });
                    }
                    layout = newLayout;
                } else if (!isNewStock) {
                    // Refresh van hetzelfde aandeel: behoud de huidige
                    // zoomstand i.p.v. terug te vallen op de standaard-view
                    // óf op Plotly's kale herteken-gedrag.
                    const existingEl = (typeof el === 'string') ? document.getElementById(el) : el;
                    const currentLayout = existingEl && existingEl.layout;
                    if (currentLayout && currentLayout.xaxis && currentLayout.xaxis.range) {
                        const newLayout = Object.assign({}, layout, {
                            xaxis: Object.assign({}, layout.xaxis, {
                                range: currentLayout.xaxis.range.slice(), autorange: false,
                            }),
                        });
                        if (currentLayout.yaxis && currentLayout.yaxis.range) {
                            newLayout.yaxis = Object.assign({}, layout.yaxis, {
                                range: currentLayout.yaxis.range.slice(), autorange: false,
                            });
                        }
                        layout = newLayout;
                    }
                }
                personalRenderedStockId = currentStockId;
            }
        } catch (e) {
            console.warn('personal range-override mislukt, val terug op standaardgedrag', e);
        }
        return originalNewPlot.call(this, el, data, layout, config);
    };
})();
</script>
"""


@app.get("/")
def root_with_personal_link():
    index_path = os.path.join(_CORE_STATIC_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("<body>", "<body>" + _PERSONAL_BANNER, 1)
    html = html.replace('<div id="chart"></div>', '<div id="chart"></div>' + _BACKFILL_BUTTON, 1)
    html = html.replace("</body>", _BACKFILL_SCRIPT + "</body>", 1)
    return HTMLResponse(html)


# --- Startup: zowel core- als personal-tabellen initialiseren -------------
# Core's eigen @app.on_event("startup") draait init_db() al; we roepen het
# hier expliciet nogmaals aan (idempotent, create_all is checkfirst) zodat
# dit ook werkt wanneer server.py buiten uvicorn's lifecycle getest wordt,
# en breiden dat uit met de (nog lege) personal-tabellen.
init_db()
init_personal_db()

