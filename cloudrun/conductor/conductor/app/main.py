from __future__ import annotations

import logging
import traceback
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .cases import router as cases_router
from .config import get_settings
from .loop import router as loop_router

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_SERVICE_ROOT / ".env")

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("conductor")

app = FastAPI(
    title="conductor",
    version="0.1.0",
    description=(
        "Autonomous trading orchestrator: candidates -> indicator snapshot -> "
        "Fable gate -> Opus synthesis -> risk governor -> execution (demo-first) "
        "-> lifecycle -> reflection."
    ),
)

_settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(loop_router)
app.include_router(cases_router)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _log.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    _log.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": f"{type(exc).__name__}: {exc}"},
    )


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse(content={"ok": True, "service": "conductor"})


@app.get("/v1/config")
def get_config() -> JSONResponse:
    s = get_settings()
    return JSONResponse(
        content={
            "execution_mode": s.execution_mode,
            "loop_enabled": s.loop_enabled,
            "bybit_trading_url": s.bybit_trading_url,
            "watchlist": s.watchlist_symbols,
            "timeframes": s.timeframes_list,
            "models": {
                "gate": s.model_gate,
                "synthesis": s.model_synthesis,
                "reflection": s.model_reflection,
            },
            "risk": {
                "risk_fraction": s.risk_fraction,
                "max_concurrent_positions": s.max_concurrent_positions,
                "max_aggregate_open_risk": s.max_aggregate_open_risk,
                "max_leverage": s.max_leverage,
                "max_margin_percent": s.max_margin_percent,
                "daily_loss_breaker_fraction": s.daily_loss_breaker_fraction,
                "weekly_loss_breaker_fraction": s.weekly_loss_breaker_fraction,
            },
        }
    )
