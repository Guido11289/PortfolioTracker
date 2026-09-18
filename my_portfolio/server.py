import os

from fastapi.responses import FileResponse, HTMLResponse

from degiro_portfolio.main import app as app
from degiro_portfolio.database import init_db

from .database import init_personal_db
from .api import system as system_api
from .api import sector as sector_api
from .api import watchlist as watchlist_api
from .api import prices as prices_api
from .api import dividends as dividends_api

app.include_router(system_api.router, prefix="/api/personal", tags=["personal"])
app.include_router(sector_api.router, prefix="/api/personal", tags=["personal", "sector"])
app.include_router(watchlist_api.router, prefix="/api/personal", tags=["personal", "watchlist"])
app.include_router(prices_api.router, prefix="/api/personal", tags=["personal", "prices"])
app.include_router(dividends_api.router, prefix="/api/personal", tags=["personal", "dividends"])

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
import degiro_portfolio.main as _core_main
_CORE_STATIC_DIR = os.path.join(os.path.dirname(_core_main.__file__), "static")


@app.get("/personal")
def personal_dashboard():
    return FileResponse(os.path.join(_WEB_DIR, "personal.html"))


@app.get("/watchlist")
def watchlist_dashboard():
    return FileResponse(os.path.join(_WEB_DIR, "watchlist.html"))


@app.get("/dividends")
def dividends_dashboard():
    return FileResponse(os.path.join(_WEB_DIR, "dividends.html"))


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
    '&nbsp;&nbsp;·&nbsp;&nbsp;'
    '<a href="/dividends" style="color:white;font-weight:600;text-decoration:none;">Dividenden</a>'
    "</div>"
)

_BACKFILL_BUTTON = (
    '<div style="margin:10px 0 20px 0;">'
    '<button onclick="personalBackfillPrices()" style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);'
    'color:white;border:none;padding:8px 16px;border-radius:6px;font-size:0.85em;font-weight:600;'
    'cursor:pointer;box-shadow:0 4px 12px rgba(102,126,234,0.3);">'
    "Backfill historische koersen (5 jaar)</button>"
    '<span id="personal-backfill-status" style="margin-left:10px;color:#718096;font-size:0.85em;"></span>'
    "</div>"
)

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

    let personalXRange = null;

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


init_db()
init_personal_db()
