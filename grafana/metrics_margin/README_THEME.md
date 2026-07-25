# Dashboard Visual Optimization for LLM Vision

When passing dashboard screenshots as PNG to vision-capable LLMs (Claude, Gemini, GPT-4o, etc.), visual presentation directly affects parsing accuracy.

## Does it matter? — Factor-by-factor analysis

### 1. Line and series colors — YES, matters

Vision LLMs distinguish colors reliably, but fail when two series on the same chart use similar auto-assigned hues. Grafana's default palette can assign adjacent greens or blues to overlapping series.

**What we did:** Added explicit contrasting color overrides to every multi-series panel:

| Panel | Series | Color |
|---|---|---|
| Rolling Correlation | `corr_24h` | yellow |
| Rolling Correlation | `corr_7d` | cyan |
| Normalized Comparison | `normalized_price_100` | green |
| Normalized Comparison | `normalized_inventory_100` | orange |

Single-series panels (Asset Price, Inventory, Stress Proxy) don't need overrides — there is nothing to confuse.

**Rule of thumb:** Any panel with ≥2 series needs explicit, high-contrast, semantically distinct colors.

### 2. Dark vs Light theme — YES, significant

| Factor | Dark theme | Light theme |
|---|---|---|
| **Text/number OCR** | Thin light text on dark bg — lower contrast | Dark text on white bg — highest contrast |
| **Thin chart lines** | Can blend into background | Stand out clearly |
| **Stat panel values** | Colored text on dark bg — generally fine | Colored text on white bg — fine |
| **Table readability** | Alternating row shading can be subtle | Sharper row boundaries |
| **Axis labels** | Often grey-on-dark, hard to parse | Black-on-white, easy to parse |

**Verdict:** Light theme produces measurably better OCR accuracy for axis labels, table values, and small text. Use light theme for LLM-destined screenshots.

The dashboard JSON currently has `"style": "dark"`. You do **not** need to change this permanently — use the URL parameter method below to capture light-theme screenshots on demand.

### 3. Font sizes — YES, critical

If the final PNG renders stat values or axis labels smaller than ~10px, LLMs frequently hallucinate digits or skip values entirely. The main risk areas:

- **Stat panels:** Large fonts by default (safe)
- **Chart axis labels:** Depend on panel height — at `h: 8` grid units with 2-per-row, these are ~14px (adequate)
- **Table cells:** Small by default — if tables are important for the LLM, capture them as separate panel screenshots at larger size
- **Legend text:** Bottom-placed legends at default size are readable at 1920px width

**No changes needed** for the current layout. If you switch to 1-per-row (see below), axis text becomes even larger.

### 4. Layout: 1-per-row vs 2-per-row — DEPENDS

| Layout | Pros | Cons |
|---|---|---|
| **2-per-row** (current) | More context per screenshot, side-by-side comparison | Smaller individual charts (~960px each at 1920w) |
| **1-per-row** | Larger charts, easier for LLM to read fine details | Taller total image, risk of downscaling by LLM |

**Verdict:** For full-dashboard screenshots, the current 2-per-row is fine at 1920px width. But for LLM consumption, the best approach is **capturing individual panels as separate images** via Grafana's render API — this gives each panel full resolution regardless of grid layout.

## Dashboard view toggles

Three view settings are available directly from the dashboard header:

### 1. Stacked View / Grid View (layout toggle)

Two provisioned dashboards share the same data, variables, and time range:

| Dashboard | UID | Layout |
|---|---|---|
| **Grid View** (default) | `metrics-margin-main` | 2 charts per row, compact |
| **Stacked View** | `metrics-margin-stacked` | 1 chart per row, full width |

Click the **Stacked View** or **Grid View** link in the dashboard header to switch. The selected asset and time range are preserved via `includeVars` and `keepTime`.

Direct URLs:

```
http://localhost:3005/d/metrics-margin-main       # grid (default)
http://localhost:3005/d/metrics-margin-stacked     # stacked
```

### 2. High Contrast (theme toggle)

Click the **High Contrast** link in the dashboard header to switch to Grafana's light theme. This gives dark lines on a white background — maximum contrast for screenshots and LLM vision.

To switch back, use the browser back button or navigate to the dashboard without `?theme=light`.

Direct URLs:

```
http://localhost:3005/d/metrics-margin-main?theme=light       # grid + light
http://localhost:3005/d/metrics-margin-stacked?theme=light    # stacked + light
```

### 3. Shared Crosshair (always on)

`graphTooltip: 2` is enabled on both dashboards. When you hover over any time series panel, a vertical crosshair line appears on **all** panels at the same timestamp. This makes it easy to correlate price movements with inventory changes and stress proxy at the exact same moment.

This is always on. To disable temporarily: **Dashboard settings** (gear icon) → **General** → **Graph tooltip** → set to **Default**.

## Practical guide: switching themes

### Method 1: URL parameter (no config change)

Append `&theme=light` or `&theme=dark` to any Grafana dashboard URL:

```
http://localhost:3005/d/metrics-margin-main?orgId=1&theme=light
http://localhost:3005/d/metrics-margin-main?orgId=1&theme=dark
```

This affects only the current browser session. No restart needed.

### Method 2: Change dashboard default

In `grafana/dashboards/metrics_margin.json`, change:

```json
"style": "dark"
```

to:

```json
"style": "light"
```

Then restart Grafana:

```bash
docker restart metrics_margin_grafana
```

### Method 3: Grafana instance-wide default

Add to `docker-compose.yml` under the `grafana` service environment:

```yaml
GF_USERS_DEFAULT_THEME: light
```

This sets the default for all users. Individual dashboards and URL params still override.

## Capturing screenshots for LLM consumption

### Option A: Browser screenshot (simplest)

1. Open dashboard with `&theme=light`
2. Set the desired time range
3. Use browser screenshot or OS screenshot tool
4. Crop to the dashboard area

### Option B: Grafana Image Renderer (automated, highest quality)

Install the renderer plugin in `docker-compose.yml`:

```yaml
# Under grafana service environment:
GF_INSTALL_PLUGINS: grafana-polystat-panel,grafana-image-renderer
GF_RENDERING_SERVER_URL: http://renderer:8081/render
GF_RENDERING_CALLBACK_URL: http://grafana:3000/
```

Add a renderer service:

```yaml
  renderer:
    image: grafana/grafana-image-renderer:latest
    container_name: metrics_margin_renderer
    restart: unless-stopped
    environment:
      ENABLE_METRICS: "true"
```

Then capture via API:

```bash
GRAFANA_URL="http://localhost:3005"
API_KEY="admin:admin"  # or use a service account token

# Full dashboard — light theme, 1920x4000
curl -u "$API_KEY" \
  "$GRAFANA_URL/render/d/metrics-margin-main?orgId=1&width=1920&height=4000&theme=light&tz=UTC" \
  -o dashboard-full.png

# Individual panel — much better for LLM analysis
# Panel IDs: 2=Price, 3=Inventory, 4=Stress, 7=Regime, 9=PriceChart,
#   10=InventoryChart, 11=StressProxy, 12=Correlation, 14=Normalized
curl -u "$API_KEY" \
  "$GRAFANA_URL/render/d-solo/metrics-margin-main/metrics-margin-main?orgId=1&panelId=14&width=1200&height=600&theme=light&var-asset=BTC" \
  -o panel-normalized.png

curl -u "$API_KEY" \
  "$GRAFANA_URL/render/d-solo/metrics-margin-main/metrics-margin-main?orgId=1&panelId=12&width=1200&height=600&theme=light&var-asset=BTC" \
  -o panel-correlation.png
```

### Option C: Capture script for all key panels

```bash
#!/bin/bash
GRAFANA_URL="http://localhost:3005"
API_KEY="admin:admin"
ASSET="${1:-BTC}"
THEME="light"
OUT_DIR="grafana/metrics_margin/docs/captures"
mkdir -p "$OUT_DIR"

declare -A PANELS=(
  [9]="price-chart"
  [10]="inventory-chart"
  [11]="stress-proxy"
  [12]="correlation"
  [14]="normalized-comparison"
)

for id in "${!PANELS[@]}"; do
  name="${PANELS[$id]}"
  curl -s -u "$API_KEY" \
    "$GRAFANA_URL/render/d-solo/metrics-margin-main/metrics-margin-main?orgId=1&panelId=$id&width=1200&height=600&theme=$THEME&var-asset=$ASSET&from=now-7d&to=now" \
    -o "$OUT_DIR/${name}-${ASSET}.png"
  echo "Captured $name → $OUT_DIR/${name}-${ASSET}.png"
done
```

## Recommended LLM prompt structure

When passing dashboard panels to an LLM, include context about what each image shows:

```
Image 1: Normalized Comparison (Base 100) for BTC — green line = price, orange line = inventory.
Both rebased to 100 at window start. Divergence indicates leverage buildup.

Image 2: Rolling Correlation — yellow = 24h, cyan = 7d.
Range: -1 to +1. Negative = borrowing against trend. Sign flips mark regime transitions.

Based on these charts, assess the current margin stress regime and directional risk.
```

Individual panels with explicit color descriptions produce significantly better LLM analysis than a single full-dashboard screenshot.

## Panel color reference

| Panel | Series | Fixed color | What it represents |
|---|---|---|---|
| Asset Price | price | auto (single series) | Spot kline close |
| Margin Available Inventory | inventory | auto (single series) | Pool supply |
| Inverted Borrow-Pressure Proxy | stress_proxy | auto (single series) | Negative z-score |
| Rolling Correlation | corr_24h | **yellow** | 24-hour rolling correlation |
| Rolling Correlation | corr_7d | **cyan** | 7-day rolling correlation |
| Normalized Comparison | normalized_price_100 | **green** | Price rebased to 100 |
| Normalized Comparison | normalized_inventory_100 | **orange** | Inventory rebased to 100 |
| Stress Regime | LOW / MEDIUM / HIGH | **green / orange / red** | Background color mapped to label |