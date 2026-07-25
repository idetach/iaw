---
title: Research Landscape — Autonomous Agent Trading (2025–2026)
tags: [strategy, research]
updated: 2026-07-25
---

# Research Landscape — Autonomous Agent Trading

Captured from the July 2026 research pass that motivated the Conductor design.
Separates the peer-reviewed signal from the social-media noise.

## The noise (what's promoted on Instagram / X)

Turnkey "AI agent" bots and viral claims: "$1k → $14k in 48h on Polymarket,"
"13x returns," fully hands-off money-printers. These embody exactly the behaviors
we prohibit ([[strategy-spec]]): survivorship-biased, gambling-style, all-in.

- The CFTC has flagged "AI trading" as a common wrapper for unrealistic schemes.
- 2025–26 live benchmarks: **smarter models do not automatically trade better.**
- "Paper Agents, Paper Gains" (arXiv): many "AI trading" projects show no evidence
  of real autonomous execution; token valuations detach from fundamentals.
- Reproducibility, transaction-cost modeling, and comparable evaluation remain
  weak across the field — great demos, thin evidence.

**Takeaway:** treat any outperformance claim with heavy skepticism; do not copy
the viral bots.

## The signal (peer-reviewed, and what we adopt)

The multi-agent research line consistently finds that value comes from
**structure**, not a cleverer entry model:

- **TradingAgents** (arXiv 2412.20138): specialized analyst roles + bull/bear
  debate + a **risk-management team** + a reflective agent improves cumulative
  return, Sharpe, and max drawdown vs. baselines.
- **FinCon**: manager–analyst hierarchy with **dual-level risk control** — the
  pattern we mirror in [[conductor-design]] and [[risk-governor-spec]].
- **FinMem / FinAgent**: layered **memory + reflection** (summarize → retrieve →
  reflect) reduces hallucination and improves decisions — the role of our
  `case_graph_analytics`.
- **FinVision** and related: multi-agent + reflective loops beat single-shot LLM
  prediction.

**Takeaway:** the edge is process discipline — risk governance + reflection +
consistency — not prediction. Design accordingly.

## How this shaped iaw

- Adopt the manager–analyst hierarchy → Conductor (manager) over existing
  analysts/executors ([[ADR-0001-conductor-merge-over-rebuild]]).
- Put real weight on the **risk governor** and **reflection**, not the entry model.
- Keep expectations honest: aim for better *risk-adjusted* behavior on demo, not
  outsized returns ([[ADR-0003-bybit-demo-trading-first]]).

## Sources

- [TradingAgents: Multi-Agents LLM Financial Trading Framework (arXiv 2412.20138)](https://arxiv.org/abs/2412.20138)
- [TradingAgents — code (TauricResearch)](https://github.com/tauricresearch/tradingagents)
- [Multi-Agents LLM Financial Trading Framework (PDF)](https://arxiv.org/pdf/2412.20138)
- [FinVision: A Multi-Agent Framework for Stock Market Prediction (arXiv 2411.08899)](https://arxiv.org/pdf/2411.08899)
- [AI Crypto Trading Agents: Do They Actually Work? (dualmedia)](https://www.dualmedia.com/ai-crypto-agents/)
- [AI Trading Agents vs Bots 2026: Hype, Risks & Real Workflow (Bitsgap)](https://bitsgap.com/blog/ai-trading-agents-vs-trading-bots-in-2026-why-smarter-isnt-safer)
- [AI Agents vs Trading Bots: What Actually Works (RPC Fast)](https://rpcfast.com/blog/ai-agents-vs-trading-bots)
- [Claude-powered bot on Polymarket — a cautionary hype example (MEXC)](https://www.mexc.com/news/946347)
