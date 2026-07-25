## Dashboards overview

Three dashboards linked via top-bar navigation buttons. All share the same `asset` / `symbol` template variables and time range.

| Dashboard | UID | Nav label | Purpose |
|---|---|---|---|
| **Inventory** (main) | `metrics-margin-main` | — | Margin pool health: stress proxy, inventory, correlation, risk config tables |
| **Stacked View** | `metrics-margin-stacked` | Stacked View | Same panels as Inventory but full-width stacked layout |
| **Flow** | `metrics-margin-pibrbs` | Flow | Money flow analytics (taker volume, net flow) and PIBRBS overlay charts |

From Inventory/Stacked you can reach Flow via the **Flow** button. From Flow you can reach Inventory via the **Inventory** button.

---

## Inventory dashboard layout

Rows:

- `Overview`
- `Correlation`
- `Margin Pool Proxy`
- `Risk / Config Tables`

Includes:

- spot price over time
- margin available inventory over time
- inverted borrow-pressure proxy
- rolling 24h and 7d correlation
- normalized comparison panel
- price index table
- isolated tier table
- collateral ratio table
- risk-based liquidation table
- config change events table
- annotations sourced from `config_change_events`

## Inventory dashboard components

### Overview row (stat panels)

| Panel | What it shows | Why it matters |
|---|---|---|
| **Latest Spot Price** | Current close price from 5-min klines | Baseline reference for all other indicators |
| **Latest Available Inventory** | Current margin pool supply for the asset | Absolute amount available for borrowing on the exchange |
| **Current Stress Proxy** | Negative z-score of inventory (higher = more stress) | Quantifies how far below normal the pool supply is. >1.5 = high stress, >0.5 = medium |
| **24h Inventory Change %** | Pool supply change over the last 24 hours | Fast-moving signal for sudden borrow demand spikes |
| **7d Inventory Change %** | Pool supply change over the last 7 days | Trend context — persistent drawdown is more significant than a single-day drop |
| **Stress Regime** | Categorical label: LOW / MEDIUM / HIGH | Quick glance risk assessment derived from the stress proxy value |

### Correlation row (time series)

| Panel | What it shows |
|---|---|
| **Asset Price** | Spot kline close prices over the selected time range |
| **Margin Available Inventory** | Margin pool supply over time |
| **Inverted Borrow-Pressure Proxy** | Stress proxy as bar chart — positive bars = below-normal inventory (borrow pressure), negative bars = above-normal (slack) |
| **Rolling Correlation** | 24h and 7d rolling Pearson correlation between price returns and inventory changes. Range: −1 to +1 |

### Margin Pool Proxy row

| Panel | What it shows |
|---|---|
| **Normalized Comparison (Base 100)** | Price and inventory both rebased to 100 at the start of the visible window. Makes divergence/convergence visually obvious on a shared scale |

### Isolated vs Cross Coverage row

Two time-series panels showing Binance-configured capacity ceilings alongside live cross-margin pool data.

| Panel | What it shows |
|---|--------------|
| **Isolated Margin Max Borrowable Capacity (Highest Tier)** | Two constant reference lines: `isolated_base_capacity` (dashed blue, left axis) and `isolated_quote_capacity` (solid orange, right axis), both from the highest configured isolated-margin tier |
| **Cross-Margin Inventory vs Isolated Max Borrowable** | Live `cross_inventory` (orange, left axis) alongside the `isolated_base_capacity` ceiling (green, left axis) — both in base-asset units so they share one scale |

#### What Base Max Borrowable and Quote Max Borrowable mean

These are **Binance-wide, pool-level lending ceilings** — they are **not per-account limits**. They represent the maximum a single borrower can draw at the highest isolated-margin tier for this specific trading pair. Binance sets and occasionally revises them as a risk management control over the lending pool.

| Field | Asset | What is being bounded | Who can borrow it | Why |
|---|---|---|---|---|
| **Base Max Borrowable** | Base asset (e.g. BTC) | How much BTC the pool can lend per position | Traders wanting to **short** (borrow BTC → sell it) | BTC borrowed and sold creates short exposure |
| **Quote Max Borrowable** | Quote asset (e.g. USDC) | How much USDC the pool can lend per position | Traders wanting to **long** (borrow USDC → buy BTC) | USDC borrowed and deployed buys the base |

Lines are **straight (constant)** by design — they only change when Binance revises its risk parameters, which is infrequent.

#### How to use these for correlation and signal analysis

**1. Pool Utilization Ratio (`cross_inventory / isolated_base_capacity`)**
Shown visually in the "Cross-Margin vs Isolated Max Borrowable" panel. When `cross_inventory` approaches `isolated_base_capacity`, the cross-margin pool is at or near the configured ceiling — meaning nearly all available supply is already lent out. A ratio close to 1 with a falling cross_inventory = pool draining toward the max. This is the most stressed state.

**2. Capacity reduction as a leading warning**
When Binance lowers `isolated_base_capacity` or `isolated_quote_capacity`, it is **tightening lending willingness** — typically because they see increased risk in that asset. A capacity cut visible as a step-down on the reference line (and logged in Config Change Events) historically precedes elevated volatility.

**3. Asymmetric capacity as directional bias**
If Binance raises `isolated_quote_capacity` (USDC lending ceiling) without raising `isolated_base_capacity` (BTC lending ceiling), they are implicitly expanding long-side capacity while capping short-side capacity — a subtle bullish bias in the risk model. The reverse signals short-side concern.

**4. Cross/Isolated gap as leverage buffer**
The gap between `cross_inventory` (live, changing) and `isolated_base_capacity` (ceiling, fixed) is the remaining headroom in the lending pool relative to the configured maximum. A narrowing gap at the same time as a rising stress proxy = confirming signal of pool stress.

### Risk / Config Tables row

| Panel | What it shows |
|---|---|
| **Margin Price Index** | Recent `priceIndex` snapshots — the reference price Binance uses for margin calculations |
| **Isolated Margin Tier** | Leverage tiers with risk ratios and max borrowable amounts per tier |
| **Cross Margin Collateral Ratio** | Collateral discount rates per asset group — determines effective collateral value |
| **Risk-Based Liquidation Ratio** | Liquidation and warning thresholds — changes here signal exchange risk parameter shifts |
| **Configuration Change Events** | Timestamped log of any changes detected in margin config endpoints |

### Annotations

Red vertical markers on all time series panels indicate **config change events** — moments when Binance changed margin tiers, collateral ratios, or liquidation parameters.

---

## Flow dashboard (PIBRBS)

Accessible via the **Flow** link from the Inventory or Stacked dashboards. Contains four collapsible sections derived from `spot_klines` and `margin_available_inventory_snapshots` data. A hidden `quote_asset` template variable auto-resolves the quote currency from the selected symbol (e.g. USDC for BTCUSDC).

### Money Flow Lite row

Built from `spot_klines` fields: `taker_buy_base_volume`, `volume`, and `close_time`. All volume metrics use base-asset units. "Sell volume" is derived as `volume − taker_buy_base_volume`.

#### Stat panels (top three rows)

| Panel | What it shows | Calculation |
|---|---|---|
| **Buy Volume (5m candle) Latest** | Taker buy volume of the most recent candle | `taker_buy_base_volume` of last row |
| **Sell Volume (5m candle) Latest** | Taker sell volume of the most recent candle | `volume − taker_buy_base_volume` of last row |
| **Buy Share % (5m candle) Latest** | Buyer share of total volume in the most recent candle | `taker_buy_base_volume / volume` |
| **Net Taker Flow (5m candle) Latest** | Net buying pressure in the most recent candle | `2 × taker_buy_base_volume − volume` (positive = net buying) |
| **… Selected Range Sum** | Aggregated totals over the Grafana time range | `SUM()` of the corresponding metric |
| **… Selected Range Avg** | Per-candle average over the Grafana time range | `AVG()` of the corresponding metric |
| **Buy Share % Selected Range Weighted Avg** | Volume-weighted average buy share | `SUM(taker_buy_base_volume) / SUM(volume)` |

#### Time series charts

| Panel | Chart type | What it shows |
|---|---|---|
| **Buy vs Sell Volume** | Mirrored bars from zero (green up / red down) | Per-candle buy and sell volume. Sell volume is negated so both series extend from a shared zero baseline. Visually highlights which side dominates each candle. |
| **Buy Share % vs Sell Share %** | Stacked area (green + red = 100%) | Each candle's volume split as a proportion. The boundary line between green and red is the buy share ratio. A rising green area means buyers are capturing more of each candle's volume. |
| **Net Taker Flow & Rolling Net Flow** | Dual line (grey + yellow) | Grey: raw per-candle net flow. Yellow: 24-candle (2h) rolling sum. The rolling line smooths noise and reveals the trend direction of net buying pressure. |
| **Flow vs Inventory Divergence (Multi-axis)** | Multi-axis compound line | Three series on separate axes — **Net Flow** (grey, left), **Inventory Δ** (orange, right), **Divergence** (purple, left). Divergence = Net Flow − Inventory Δ. When divergence grows, spot buying/selling is not being reflected in the margin pool, suggesting off-exchange or spot-only activity. |

### PIBRBS row

Overlays five core series on shared time axes: **P**rice, **I**nventory, **B**orrow proxy, **R**epay proxy, **B**uy/**S**ell % change.

| Panel | Series | What it shows |
|---|---|---|
| **Combined: Price, Inventory, Borrow/Repay Proxy, Buy/Sell Change** | All five | Master view. Price (green line, left axis), Inventory (orange line, right axis), Borrow proxy (red bars down from zero, right axis), Repay proxy (blue bars up from zero, right axis), Buy/Sell Log Change (thin grey line, left axis). |
| **Price & Buy/Sell Change** | Price + Buy/Sell Log Change | Isolates the relationship between price movement and shifts in the buy-to-sell ratio. Buy/Sell Log Change = `ln(ratio / prev_ratio) × 100` where ratio = `taker_buy_base_volume / sell_volume`. Uses natural log instead of percentage change for symmetric scaling — equal-magnitude moves in opposite directions produce equal-magnitude values (e.g. ratio doubling = +69, halving = −69). Outlier spikes remain visible but no longer distort the axis asymmetrically. |
| **Price, Inventory & Borrow/Repay Proxy** | Price + Inventory + Borrow/Repay | Isolates the supply-side picture. Borrow proxy = negative inventory drops (someone borrowed). Repay proxy = positive inventory jumps (someone repaid). |

#### Series definitions

| Series | Source | Formula |
|---|---|---|
| **Price** | `spot_klines.close` | Raw close price |
| **Inventory** | `margin_available_inventory_snapshots.available_inventory` | Raw pool supply |
| **Borrow proxy** | Inventory snapshots | `−MAX(0, prev_inventory − inventory)` — shown as red bars below zero |
| **Repay proxy** | Inventory snapshots | `MAX(0, inventory − prev_inventory)` — shown as blue bars above zero |
| **Buy/Sell Log Change** | `spot_klines` | `ln(ratio / prev_ratio) × 100` where ratio = `taker_buy_base_volume / (volume − taker_buy_base_volume)`. Uses log-change instead of percentage change: symmetric around zero, no upper-bound asymmetry. A value of +69 means the buy/sell ratio doubled; −69 means it halved. Small changes (±5) are approximately equal to percentage changes. |

### Directional Margin Map row

Separates **base-side borrowing** from **quote-side borrowing** to resolve the directional ambiguity in the original inventory panels. For BTCUSDC: BTC inventory drawdown suggests short pressure (base borrowed to sell), while USDC inventory drawdown suggests long pressure (quote borrowed to buy BTC). Uses a hidden `quote_asset` template variable auto-resolved from the selected symbol.

| Panel | Chart type | What it shows |
|---|---|---|
| **Price, Base Inventory & Quote Inventory** | Multi-axis lines (3 Y axes: price left, base inv right, quote inv right) | Price (green), base asset inventory (orange), quote asset inventory (blue). Each axis has independent scale in raw units. Divergence between base and quote drawdowns reveals directional leverage bias. |
| **Base Borrow / Repay Proxy** | Mirrored bars from zero (red down / blue up) | Same LAG-based diff as PIBRBS but isolated to the **base asset** (e.g. BTC). Red bars = base borrowed (short pressure). Blue bars = base repaid (short covering). |
| **Quote Borrow / Repay Proxy** | Mirrored bars from zero (dark orange down / cyan up) | Same logic for the **quote asset** (e.g. USDC). Dark orange bars = quote borrowed (long pressure). Cyan bars = quote repaid (long unwind / deleveraging). |
| **Directional Stress Ratio** | Oscillator centered at zero (continuous color scale) | `quote_stress_z − base_stress_z`. Computed from raw inventory using 288-point rolling z-scores. Positive = quote borrow pressure dominates → **long bias**. Negative = base borrow pressure dominates → **short bias**. |

#### Directional signal interpretation

| Pattern | Meaning |
|---|---|
| **Base inventory falling, quote stable** | Base being borrowed → short-biased pressure |
| **Quote inventory falling, base stable** | Quote being borrowed to buy base → long-biased pressure |
| **Both falling** | Both sides leveraging — high-stress environment, watch for liquidation cascades |
| **Both recovering** | Deleveraging across both sides — selling/covering pressure may be exhausting |
| **Directional Stress > +1** | Strong quote-side stress → high long bias |
| **Directional Stress < −1** | Strong base-side stress → high short bias |

### Quote Flow & Z-scores row

Adds quote-denominated flow metrics and statistical normalization for cross-asset comparability and outlier detection.

| Panel | Chart type | What it shows |
|---|---|---|
| **Net Taker Flow & Rolling Net Flow (Quote Terms)** | Dual line (grey + yellow) | Same structure as the base-unit net flow panel but in **quote currency** (e.g. USDC). Formula: `2 × taker_buy_quote_volume − quote_volume`. Makes cross-asset flow comparison meaningful. |
| **Net Flow Z-score (24h rolling)** | Oscillator line centered at zero | `(net_flow − rolling_mean) / rolling_std` over a 288-candle (24h) window. Values > +2 = unusually aggressive buying. Values < −2 = unusually aggressive selling. |
| **Volume Shock (24h Z-scores)** | Three bar series | Z-score of total volume (grey), buy volume (green), sell volume (red). All on 24h rolling window. Spikes identify candles with statistically significant volume — filters noise from low-volume oscillation. |
| **Flow Regime Shift** | Multi-axis compound (4 series, 2 Y axes) | Left axis: raw net flow (grey) + 2h rolling net flow (yellow, thick). Right axis: buy share % (green) + buy/sell log change (orange). Shows when spot flow flips from seller-dominant to buyer-dominant or vice versa. |

---

## Signals for price movement prediction

### Primary signal: inventory drawdown diverging from price

The strongest predictive setup occurs when the **Normalized Comparison** panel shows inventory falling while price holds steady or rises. This indicates hidden leverage buildup — traders are borrowing aggressively to go long. The larger the divergence, the more fragile the structure:

- **Inventory drawdown + price stable/rising** → Crowded leveraged long. A price dip can trigger cascading liquidations, amplifying the sell-off.
- **Inventory recovering + price falling** → Deleveraging in progress. Forced closures return supply to the pool. Selling pressure may be exhausting.

**Important directional caveat**: The above applies to the **combined** (base-only) inventory view. For precise direction, use the **Directional Margin Map** panels which separate base vs quote:

- **Base inventory drawdown** (e.g. BTC pool draining) = base being borrowed, usually **short-biased** pressure
- **Quote inventory drawdown** (e.g. USDC pool draining) = quote being borrowed to buy base, usually **long-biased** pressure
- A combined inventory drawdown with price rising is only reliably a "crowded long" signal when the **quote-side** drawdown dominates (check the Directional Stress Ratio)

### Correlation regime reading

| Correlation value | Meaning | Implication |
|---|---|---|
| **Strongly negative** (< −0.5) | Price up → inventory down (or vice versa) | Active margin borrowing against the trend. Classic stress buildup phase. |
| **Near zero** (−0.2 to +0.2) | No systematic relationship | Neutral — margin activity is not directionally aligned with price. |
| **Strongly positive** (> +0.5) | Price and inventory move together | Deleveraging or re-collateralization — positions being unwound. Often seen during or after liquidation cascades. |

Watch for **correlation sign flips** — a shift from negative to positive often marks the transition from leverage buildup to forced unwind.

### Stress proxy thresholds

| Stress Proxy | Regime | Interpretation |
|---|---|---|
| < 0.5 | LOW | Normal pool supply. No unusual borrowing pressure. |
| 0.5 – 1.5 | MEDIUM | Elevated borrowing. Pool is thinning. Monitor closely. |
| > 1.5 | HIGH | Significant supply depletion. Pool is ≥1.5 standard deviations below its rolling mean. Conditions are fragile. |

### Config change events as leading indicators

Exchange-initiated changes to margin tiers, collateral ratios, or liquidation parameters often **precede volatility**. When Binance tightens risk parameters (raises liquidation ratios, lowers max borrowable), it typically signals the exchange sees elevated risk before it is reflected in price.

### Combining signals

The highest-conviction setup combines multiple dashboard elements:

1. **Stress regime** at MEDIUM or HIGH
2. **Inventory drawdown** visible in the normalized comparison (diverging below price)
3. **Rolling correlation** deeply negative (leverage building against trend)
4. **Config change** annotation appearing (exchange tightening parameters)

This combination suggests a fragile market structure where a relatively small adverse price move can trigger outsized liquidation cascades.

### Money Flow Lite signals

#### Net Taker Flow direction

| Condition | Reading | Trade implication |
|---|---|---|
| **Net Flow persistently positive** | Taker buyers dominate candle after candle | Spot demand is genuine. Supports long bias. |
| **Net Flow persistently negative** | Taker sellers dominate | Sustained selling pressure. Supports short bias or staying flat. |
| **Net Flow flipping from positive to negative** | Buyer exhaustion | Momentum shift — consider closing longs or initiating shorts. |
| **Net Flow flipping from negative to positive** | Seller exhaustion | Potential reversal — consider closing shorts or initiating longs. |

#### Rolling Net Flow (yellow line) as trend filter

The 24-candle (2h) rolling sum acts as a momentum smoothing filter:

- **Rolling line rising and above zero** → Sustained buying wave. Trend favors longs.
- **Rolling line falling and below zero** → Sustained selling wave. Trend favors shorts.
- **Rolling line crossing zero** → Momentum regime change. Key signal for entry/exit timing.

#### Buy Share % reading

| Buy Share | Meaning |
|---|---|
| **> 55% sustained** | Buyers are aggressive. Bullish flow imbalance. |
| **< 45% sustained** | Sellers are aggressive. Bearish flow imbalance. |
| **Oscillating 48–52%** | Balanced market — no directional edge from flow alone. |

A sudden spike in buy share from a balanced baseline (e.g. 50% → 60%) often precedes a short-term price move up, and vice versa.

#### Flow vs Inventory Divergence

This is the most actionable panel in Money Flow Lite because it connects spot-side activity (net taker flow) with margin-side activity (inventory changes).

| Pattern | Interpretation | Trade implication |
|---|---|---|
| **Divergence rising (purple up)** | Net buying exceeds inventory recovery | Spot demand is outpacing margin pool replenishment. Bullish pressure building. Favors long. |
| **Divergence falling (purple down)** | Net selling exceeds inventory drawdown | Spot selling is outpacing borrowing. Bearish pressure. Favors short. |
| **Divergence near zero** | Flow and inventory changes are balanced | No edge from this signal. |
| **Net Flow positive + Inventory Δ negative** | Buyers on spot while borrowers draw down the pool | Double bullish — both spot and margin participants are positioned long. Strong long signal, but also fragile if sentiment flips. |
| **Net Flow negative + Inventory Δ positive** | Sellers on spot while borrowers repay | Double bearish unwind — deleveraging plus spot selling. Continuation of downtrend likely. |

### PIBRBS signals

#### Buy/Sell Log Change (grey line) as momentum oscillator

This series measures the candle-over-candle log-change in the buy-to-sell ratio (`ln(ratio / prev_ratio) × 100`). It functions as a high-frequency momentum oscillator with symmetric scaling — equal moves up and down produce equal magnitudes.

- **Spikes above +5** → Sudden shift toward buyers. Short-term bullish.
- **Spikes below −5** → Sudden shift toward sellers. Short-term bearish.
- **Large spikes (±50 to ±300+)** → Extreme outlier candles where buy/sell balance shifted dramatically. These remain fully visible and indicate candles where one side dominated volume almost entirely.
- **Sustained drift in one direction** → Trending flow imbalance. Stronger signal than isolated spikes.

Reference values: +69 ≈ ratio doubled (2× more buyers), −69 ≈ ratio halved, +230 ≈ 10× shift, −230 ≈ 0.1× shift.

#### Borrow/Repay proxy reading

| Pattern | Meaning | Trade implication |
|---|---|---|
| **Cluster of red (borrow) bars** | Rapid inventory drawdown — margin borrowing accelerating | Leveraged positions building. If price is rising, crowded long. If price is falling, short-sellers borrowing to add. |
| **Cluster of blue (repay) bars** | Inventory recovering — positions being closed or collateral returned | Deleveraging phase. Selling pressure from forced closures may be near exhaustion. |
| **Borrow bars + price rising** | Traders borrowing to go long (or short-sellers being squeezed into repaying) | Fragile bullish — works until it doesn't. Watch for repay bars signaling the unwind. |
| **Borrow bars + price falling** | Traders borrowing to short (or longs being liquidated) | Bearish momentum reinforced by leverage. |
| **Repay bars + price falling** | Forced unwind of longs | Liquidation cascade may be underway. Look for repay bars to slow as a bottom signal. |
| **Repay bars + price rising** | Short-sellers closing (covering) | Short squeeze dynamics. Bullish until repay activity subsides. |

### Cross-dashboard signal synthesis

The strongest setups combine signals from both the **Inventory** (main) dashboard and the **Flow** (PIBRBS) dashboard:

#### High-conviction long setup

1. **Inventory dashboard**: Stress regime LOW or MEDIUM, inventory stable or recovering
2. **Flow dashboard**: Net Taker Flow persistently positive, rolling net flow above zero and rising
3. **Flow dashboard**: Buy Share % > 55%
4. **PIBRBS**: Buy/Sell Log Change trending positive, no cluster of borrow bars (leverage not excessive)
5. **Flow dashboard**: Divergence (purple) rising — spot demand exceeding inventory change

This combination shows genuine spot-driven demand without excessive leverage, the healthiest form of bullish pressure.

#### High-conviction short setup

1. **Inventory dashboard**: Stress regime MEDIUM or HIGH, inventory drawdown accelerating
2. **Flow dashboard**: Net Taker Flow persistently negative, rolling net flow below zero and falling
3. **Flow dashboard**: Buy Share % < 45%
4. **PIBRBS**: Cluster of borrow bars (red) while price rises — leverage building on the long side
5. **Inventory dashboard**: Rolling correlation deeply negative (leverage diverging from price)

This combination shows leveraged longs building against weakening spot demand — the classic setup for a liquidation cascade.

#### Reversal detection

Watch for these transitions across dashboards:

- **Long → short reversal**: Rolling net flow crosses below zero + repay bars appear (longs unwinding) + stress proxy rising → bearish shift
- **Short → long reversal**: Rolling net flow crosses above zero + borrow bars stop (selling pressure exhausted) + divergence flipping positive → bullish shift
- **Confirmation**: On the Inventory dashboard, a correlation sign flip (negative → positive) often confirms the regime change

#### Directional margin map signals

Use the **Directional Margin Map** row on the Flow dashboard for precise long/short bias:

- **Directional Stress Ratio rising above +1**: Quote pool under stress → long-biased leverage building. Confirm with rolling net flow positive and buy share > 52%.
- **Directional Stress Ratio falling below −1**: Base pool under stress → short-biased leverage building. Confirm with rolling net flow negative and buy share < 48%.
- **Quote borrow cluster + base repay cluster**: Short-to-long rotation — shorts covering (base repaid) while new longs open (quote borrowed).
- **Base borrow cluster + quote repay cluster**: Long-to-short rotation — longs unwinding (quote repaid) while new shorts open (base borrowed).
- **Net Flow Z-score > +2 with quote borrow bars**: Strong conviction long signal — statistically unusual buying pressure backed by leveraged demand.
- **Net Flow Z-score < −2 with base borrow bars**: Strong conviction short signal — statistically unusual selling pressure backed by leveraged shorting.
- **Volume Shock spike (any z-score > 3)**: Unusually large candle — check whether buy or sell z-score dominates to determine direction of the shock.

---

## On-chain data sources for next price move detection

Margin inventory analysis (this system) tracks **CEX lending pool** activity. On-chain analytics adds a second layer: **actual capital movements recorded on the blockchain** — wallet flows, exchange deposits/withdrawals, holder behavior, miner activity. These are complementary layers with different lead times and signal types.

### Signal layers and their lead times

| Layer | Examples | Typical lead time | What it measures |
|---|---|---|---|
| **On-chain holder flows** | Exchange inflow/outflow, SOPR, MVRV | Hours to days | Accumulated capital positioning of all market participants |
| **Derivatives structure** | OI, funding rates, liquidation maps | Minutes to hours | Leverage positioning and crowdedness |
| **Margin pool inventory** | This system | Minutes | CEX lending demand (this system's core edge) |
| **Spot taker flow** | Net flow, buy share % | Real-time | Immediate execution-side pressure |

The highest-conviction setups stack signals from all four layers.

---

### Tier 0: All-in-one platform (consider first)

#### Alphractal (https://alphractal.com · API: https://api.alphractal.com)
**Best for**: Replacing Glassnode + CryptoQuant + Coinglass with a single API. Covers on-chain, derivatives, sentiment, macro, and market data under one key. Free to start.

From the live API spec, confirmed categories:

| Category | Count | Notable metrics |
|---|---|---|
| **On-chain** | 300+ | SOPR, LTH/STH supply, address balance distributions, exchange flows, UTXO age bands |
| **Derivatives** | 60+ | OI, funding rates, liquidations, long/short ratios, perpetual futures |
| **Mining** | + proprietary | Hash rate, difficulty, Puell Multiple + `capitulation_oscillator`, `hash_momentum_score`, `mining_equilibrium`, `network_stress` |
| **Sentiment** | 80+ | Fear & Greed, Google Trends, Twitter/X, 4chan |
| **Macro** | 300+ | DXY, S&P 500, Treasury yields, global liquidity — **unique, no other platform bundles this** |
| **Proprietary models** | 23 | Pi Cycle, CVDD, Reserve Risk, Accumulation Heatmaps, `smart_money_flow` |
| **Screener** | 100+ chart types | Per-asset OI trends, buy/sell volume by timeframe, LSR, MA distances |

**API**: REST, OpenAPI 3.1. Auth via `X-Api-Key` header. Pattern: `GET https://api.alphractal.com/{asset}/{category}/{metric}?startDate=...&endDate=...`

**Advantages over the Tier 1 stack below**:
- One API replaces Glassnode + CryptoQuant + Coinglass (users explicitly report switching from all three)
- Macro data (DXY, rates) bundled — none of the specialist platforms offer this
- Proprietary derived signals already computed — `capitulation_oscillator` etc. would require raw data + computation from Glassnode
- 1,000+ assets — broader than Glassnode/CryptoQuant which focus on BTC/ETH
- AI layer (Alpha AI) for natural-language querying of all 1,500+ metrics
- Free tier — lower barrier to prototype than Glassnode's paid-only historical data

**Weaknesses**:
- Data provenance less transparent than Glassnode (which publishes full methodology per metric)
- Newer platform — data quality edge cases harder to verify vs Glassnode's 7-year track record
- Liquidation heatmap visual tool not as mature as Coinglass's UI
- No entity-level wallet intelligence (Arkham's territory)

**Verdict**: Best single starting point for the on-chain data extension. Prototype with the free tier. Supplement with Glassnode only if you need auditable methodology for specific metrics (SOPR, LTH/STH) in production.

---

### Tier 1 APIs — systematic quantitative analytics

#### Glassnode (https://glassnode.com)
**Best for**: Comprehensive BTC and ETH on-chain analysis. The most data-complete platform for systematic signal construction.

| Metric | API path example | Signal logic | Lead time |
|---|---|---|---|
| **Exchange Net Position Change** | `/v1/metrics/distribution/exchange_net_position_change` | Net BTC moving to/from all exchanges. Sustained outflow (negative) = accumulation → bullish. Inflow spike = distribution → bearish. | 6–48h |
| **SOPR** (Spent Output Profit Ratio) | `/v1/metrics/indicators/sopr` | >1 = average moved coin is in profit (sellers may realize gains). <1 = selling at a loss (capitulation — often near bottoms). | 12–72h |
| **Short-Term Holder SOPR** | `/v1/metrics/indicators/sopr_less_155d` | STH SOPR dipping below 1 then recovering = local bottom signal. Staying above 1 after a rally = healthy trend. | 2–24h |
| **Long-Term Holder SOPR** | `/v1/metrics/indicators/sopr_more_155d` | LTH SOPR below 1 = long-term holders capitulating (rare, strong bottom signal). >1 with high values = distribution phase. | Days to weeks |
| **MVRV Z-Score** | `/v1/metrics/market/mvrv_z_score` | Market cap vs Realized cap normalized by std. >7 = historically overvalued (past tops). <0 = historically undervalued (past bottoms). | Weeks (structural) |
| **Exchange Stablecoin Ratio** | `/v1/metrics/distribution/exchange_stablecoin_supply_ratio` | High stablecoin reserves on exchanges relative to BTC market cap = dry powder for buying. Rising = bullish dry powder building. | 1–7 days |
| **Estimated Leverage Ratio** | `/v1/metrics/derivatives/futures_estimated_leverage_ratio` | OI / exchange reserves. High = system is over-leveraged → fragile, prone to cascades. | Hours |

**API**: REST (`https://api.glassnode.com/v1/metrics/{category}/{metric}?a=BTC&api_key=...`). Requires API key. Tier 1 plan (~$39/mo) covers most of the above.

---

#### Coinglass (https://coinglass.com)
**Best for**: Derivatives micro-structure — liquidation maps, OI aggregation, funding rates. Free tier is highly functional.

| Metric | What it shows | Signal logic |
|---|---|---|
| **Liquidation Heatmap** | Price levels with concentrated liquidation clusters | Price approaching a cluster = likely acceleration through that level (engine for cascade or squeeze). Critical for entry/exit placement. |
| **Open Interest** | Aggregate OI across all major exchanges | OI rising with price = healthy. OI rising with flat price = leverage buildup → fragile. OI dropping with price = forced deleveraging (capitulation or correction). |
| **Funding Rate** | Per-exchange and aggregated 8h funding | Persistent positive (>0.05% per 8h) = longs paying heavily → crowded. Will mean-revert via flush. Persistent negative = shorts crowded → squeeze setup. |
| **Long/Short Ratio** | % of accounts long vs short on Binance futures | Extreme long ratio (>70%) = contrarian bearish. Extreme short ratio (<30% long) = contrarian bullish. |

**API**: `https://open-api.coinglass.com/public/v2/...` — free tier with rate limits. Premium unlocks higher resolution.

---

#### CryptoQuant (https://cryptoquant.com)
**Best for**: Exchange-specific inflow/outflow, miner behavior, stablecoin supply.

| Metric | Signal logic |
|---|---|
| **Exchange Inflow (all exchanges)** | Large sudden inflows (BTC moving onto exchanges) = intent to sell. Often precedes selling within 1–6h. |
| **Exchange Outflow** | Sustained outflow = holders withdrawing to self-custody (accumulation). Bullish medium-term. |
| **Miner Reserve** | Miners reducing reserves (selling) = supply pressure. Often front-runs volatility. |
| **Stablecoin Exchange Inflow** | Stablecoins moving onto exchanges = fresh buying power arriving. Short-term bullish. |

**API**: REST, requires subscription.

---

### Tier 2 APIs — specialized or freemium

#### Arkham Intelligence (https://arkhamintelligence.com)
**Best for**: Entity-level intelligence. Maps blockchain addresses to real-world entities (exchanges, funds, market makers, known whales). Best used as a surveillance complement, not a systematic signal source.

| Use case | What it enables |
|---|---|
| **Whale tracking** | Alert when labeled wallets (Jump, known miners, OTC desks) move large amounts |
| **Exchange cold wallet monitoring** | Track exchange reserve movements at the wallet level, not just aggregate |
| **Smart money alerts** | When known profitable addresses accumulate or distribute |

**Comparison vs Glassnode**: Glassnode excels at systematic, time-series, statistically normalizable signals. Arkham excels at surveillance and actor-specific intelligence. They answer different questions — Glassnode answers "what is the aggregate doing?", Arkham answers "what is *this specific actor* doing?" For algorithmic trading setups, Glassnode is more directly actionable; Arkham adds context.

#### Whale Alert (https://whale-alert.io)
Real-time alerts for transactions >$X on-chain. Simple noise layer — useful as a trigger for checking deeper data, not as a signal itself. API + Telegram bot.

#### Nansen (https://nansen.ai)
Best for Ethereum, ERC-20, and DeFi analytics. Smart money wallet labels (funds, DEX whales). Less relevant for BTC-centric analysis. Strong for altcoin smart-money positioning.

---

### Priority metrics to fetch — ranked by signal quality

#### Short-term (1–8 hours)

1. **Exchange large inflow alert** (Glassnode / CryptoQuant) — spike of >500 BTC arriving on exchange in 1h often precedes selling within 1–6h
2. **Funding rate** (Coinglass) — rate >+0.10% per 8h signals crowded longs → flush imminent
3. **Liquidation heatmap proximity** (Coinglass) — price within 1% of a major liquidation cluster means the cluster is the next magnetic target
4. **Stablecoin exchange inflow** (CryptoQuant) — fresh USDC/USDT arriving = buying fuel → short-term bullish
5. **Volume Shock Z-score** (already collected) — statistically unusual candle validates other on-chain signals

#### Mid-term (1–7 days)

1. **Exchange Net Position 7d trend** (Glassnode) — sustained outflow = structural accumulation → medium-term bullish
2. **SOPR 7d trend** (Glassnode) — sustained >1 = distribution. Sustained <1 = capitulation exhausting
3. **LTH SOPR** (Glassnode) — LTH capitulating (<1) = strong bottom signal; LTH distributing heavily = top signal
4. **OI trend relative to price** (Coinglass) — divergence between OI growth and price growth = leverage buildup
5. **Miner reserve 7d change** (CryptoQuant) — large miner outflow → supply increase incoming

---

### How to integrate into this system

#### Database schema extension

Add an `onchain_metrics` table using the same pattern as `derived_metrics`:

```sql
CREATE TABLE onchain_metrics (
    id          BIGSERIAL,
    collected_at TIMESTAMPTZ NOT NULL,
    asset       TEXT        NOT NULL,
    metric_name TEXT        NOT NULL,
    metric_value DOUBLE PRECISION,
    source      TEXT        NOT NULL,  -- 'glassnode', 'coinglass', etc.
    window_label TEXT,
    metadata    JSONB
);
```

#### Correlation approach

- Z-score normalize all on-chain signals over a 24h/7d window (same as net flow Z-scores already in this system)
- Plot each signal alongside spot price on a shared time axis
- Compute **lead correlation**: correlate signal at time `t` against price return at `t+N` for N = 1h, 4h, 12h, 24h, 48h to find optimal leading window
- Prioritize signals with statistically significant lead correlation at N > 0 (predictive rather than coincident)

#### Recommended starting stack

| Data source | What to add | Why |
|---|---|---|
| **Alphractal** (start here) | Exchange flows + SOPR + OI + Funding Rate + Macro (DXY) | Single API covering Glassnode + CryptoQuant + Coinglass. Free tier to prototype. |
| **Glassnode** (optional upgrade) | Same metrics as Alphractal but with published methodology | Add if you need auditable data provenance for SOPR/LTH signals in a production system |
| **Coinglass** (optional) | Liquidation heatmap visual UI | Add only if you need the visual heatmap tool; the underlying data is in Alphractal's API |
| **This system** | Margin inventory + spot flow (already running) | CEX lending demand — the existing edge not available from any on-chain API |

Arkham is complementary for entity/whale surveillance (different problem from aggregate analytics). Nansen is worth adding if you trade ETH/DeFi tokens.