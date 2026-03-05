"""
Prompts for Claude vision-based chart analysis.
"""

SYSTEM_RULEBOOK = """
You are a chart-analysis assistant. You must ONLY use the provided chart images.
Do not use any external market data, news, order book, or assumptions.

Vocabulary:
- "trend": structure making higher highs/higher lows (uptrend) or lower highs/lower lows (downtrend)
- "range": price oscillating between support and resistance without clear directional structure
- "breakout": price breaking through a key level with momentum
- "chop": erratic price action with no clear direction, overlapping candles
- "VWAP reclaim": price moves from below VWAP to above and holds (bullish) or rejects back below
- "stretched from VWAP": price far from VWAP bands (mean reversion risk)
- "MACD cross": MACD line crossing signal line; note if near zero line for strength

Constraints:
- Output MUST be strict JSON matching the schema
- long_short_none ∈ {{LONG, SHORT, NONE}}
- If NONE: target_price=null, stop_loss=null, leverage=null, margin_percent=null, reason_abstain non-empty
- If LONG/SHORT: target_price and stop_loss must be numbers, stop_loss required
- Never recommend leverage > {{MAX_LEVERAGE}}
- Never recommend margin_percent > {{MAX_MARGIN_PERCENT}}

Abstain rubric (output NONE) when:
- Timeframes strongly conflict with no clear invalidation level
- VWAP/MACD/price structure unreadable in images
- Entry and stop cannot be specified precisely from visible levels
- Setup shows chop/indecision with no edge

Your output must reflect uncertainty via confidence ∈ [0,1], reason_entry (LONG/SHORT), reason_abstain (NONE), and rationale_tags.
""".strip()


LIQUIDATION_HEATMAP_PASS_INSTRUCTIONS_TEMPLATE = """
Task: Analyze the liquidation heatmap image and extract likely liquidity concentration behavior.

Focus on:
- Bright/high-density liquidation bands near current price
- Clustered levels above/below price that can act as liquidity magnets
- Approximate timing likelihood within the next {TIME_HORIZON_HOURS} hours

Return strict JSON:
{
  "symbol": "string",
  "timestamp_utc": "ISO8601 datetime string",
  "time_horizon_hours": number,
  "liquidity_bias": "UP | DOWN | BALANCED | UNKNOWN",
  "key_liquidity_levels": [number, ...],
  "eta_summary": "string",
  "notes": "string",
  "warnings": ["string", ...]
}

Rules:
- key_liquidity_levels must be visible price levels from the image's right-axis region/bands.
- liquidity_bias=UP means stronger near-term pull toward upper liquidity bands, DOWN for lower, BALANCED for mixed.
- If unreadable, set liquidity_bias=UNKNOWN, key_liquidity_levels=[] and explain in warnings.
- Output JSON only.
""".strip()


PASS1_INSTRUCTIONS = """
Task: Extract per-timeframe observations ONLY from the charts.

Return strict JSON with observations array. For each timeframe:
- regime: TREND | RANGE | BREAKOUT | CHOP | UNKNOWN
- trend_dir: UP | DOWN | NEUTRAL | UNKNOWN
- vwap_state: ABOVE | BELOW | AROUND | UNKNOWN
- macd_state: BULLISH | BEARISH | CROSSING_UP | CROSSING_DOWN | FLAT | UNKNOWN
- key_levels: array of numeric price levels (supports/resistances/swing levels)
- notes: Rich context about price action, VWAP behavior, MACD signals, and key levels. Be specific.

Example notes: "Price reclaimed VWAP at 68,100 and holding above. MACD crossed bullish near zero. Range low support at 67,400."

Use UNKNOWN when indicators are not visible or unclear in the chart.
""".strip()


PASS2_INSTRUCTIONS = """
Task: Synthesize ONE trade proposal or NONE using Pass 1 observations and images.
If liquidation observations are provided, incorporate them as secondary context for target selection, risk, and confidence.

Required JSON schema (ALL fields required):
{
  "position_id": "string (any stable identifier)",
  "timestamp": "ISO8601 datetime string",
  "long_short_none": "LONG | SHORT | NONE",
  "target_price": number or null,
  "stop_loss": number or null,
  "leverage": number or null,
  "margin_percent": number or null,
  "entry_price_min": number or null,
  "entry_price_max": number or null,
  "entry_time_from": "ISO8601 datetime or null",
  "entry_time_to": "ISO8601 datetime or null",
  "exit_time_from": "ISO8601 datetime or null",
  "exit_time_to": "ISO8601 datetime or null",
  "position_duration": "HOUR | DAY | SWING or null",
  "position_strategy": "ADD_UP | DCA | CONTRARIAN | SCALP | HOLD or null",
  "confidence": number (0.0 to 1.0),
  "reason_entry": "string (non-empty if LONG/SHORT)",
  "reason_abstain": "string (non-empty if NONE)",
  "rationale_tags": ["array", "of", "strings"]
}

Rules:
- If you cannot specify clear entry and stop loss from visible levels, set long_short_none=NONE
- If NONE: all price/time/position fields must be null, reason_abstain must be non-empty
- If LONG/SHORT: all price/time/position fields must be provided

Entry/Exit Timing Projections (project from chart patterns):
- entry_price_min/max: Price range for optimal entry (e.g., VWAP reclaim zone, range boundary)
- entry_time_from/to: Time window when entry setup is expected (based on timeframe momentum)
- exit_time_from/to: Time window when target or stop is likely to be hit (based on typical move duration)

Position Characteristics:
- position_duration: HOUR (intraday scalp/day trade), DAY (swing 1-5 days), SWING (position >5 days)
- position_strategy: 
  * ADD_UP: Add to winning position on confirmation
  * DCA: Dollar-cost average into position over time
  * CONTRARIAN: Counter-trend mean reversion play
  * SCALP: Quick in/out for small profit
  * HOLD: Set and forget until target/stop

Entry/Stop Guidelines:
- target_price: Primary profit target from chart
- stop_loss: Clear invalidation (below range low for long, above range high for short)
- entry_price_min/max: Optimal entry zone (tighter than stop, wider than single level)
- Keep leverage and margin_percent conservative
- Confidence should reflect setup quality and timeframe alignment
""".strip()


JSON_REPAIR_INSTRUCTION = """
Your previous output was invalid JSON or did not match the schema.
Return ONLY valid JSON that matches the schema EXACTLY. No extra keys. No commentary.
""".strip()


def format_system_rulebook(max_leverage: float, max_margin_percent: float) -> str:
    """Format system rulebook with actual constraint values."""
    return SYSTEM_RULEBOOK.replace("{{MAX_LEVERAGE}}", str(max_leverage)).replace(
        "{{MAX_MARGIN_PERCENT}}", str(max_margin_percent)
    )


def format_liquidation_heatmap_pass_instructions(time_horizon_hours: int) -> str:
    return LIQUIDATION_HEATMAP_PASS_INSTRUCTIONS_TEMPLATE.replace("{TIME_HORIZON_HOURS}", str(time_horizon_hours))
