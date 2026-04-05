from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


class CaptureRequest(BaseModel):
    case_id: str = Field(min_length=6)
    symbol: str = Field(min_length=1)
    provider: str | None = None
    vision_model_pass1: str | None = None
    vision_model_pass2: str | None = None
    per_tf_windows: bool | None = None
    tv_resize_and_dismiss_banner: bool | None = None
    tv_calibrate_window_size: bool | None = None
    show_tv_window_on_calibration: bool | None = None
    dismiss_tv_banner: bool | None = None
    include_liquidation_heatmap: bool = False
    liquidation_heatmap_window_owner: str | None = None
    liquidation_heatmap_window_title: str | None = None
    liquidation_heatmap_refresh_wait_seconds: float | None = Field(default=None, ge=0.0, le=30.0)
    liquidation_heatmap_time_horizon_hours: int | None = Field(default=None, ge=1, le=168)
    http_timeout_seconds: float | None = Field(default=None, ge=5.0, le=900.0)
    app_window: str | None = None
    debug_env: bool | None = None


class ResizeWindowsDismissTVBannerRequest(BaseModel):
    symbol: str | None = None
    tv_resize_and_dismiss_banner: bool | None = None
    tv_calibrate_window_size: bool | None = None
    show_tv_window_on_calibration: bool | None = None
    dismiss_tv_banner: bool | None = None
    tv_window_width: int | None = Field(default=None, ge=1, le=8000)
    tv_window_height: int | None = Field(default=None, ge=1, le=8000)
    tv_window_resize_wait_seconds: float | None = Field(default=None, ge=0.0, le=10.0)
    window_owner: str | None = None
    window_title_template: str | None = None
    debug_env: bool | None = None


class ArrangePlacement(BaseModel):
    window_id: int | None = Field(default=None, ge=1)
    owner_name: str = Field(min_length=1)
    window_name: str = Field(min_length=1)
    col: int = Field(ge=0, le=7)
    row: int = Field(ge=0, le=3)


class ArrangeWindowsRequest(BaseModel):
    placements: list[ArrangePlacement] = Field(default_factory=list)
    step_x: int = Field(default=1138, ge=1, le=5000)
    step_y: int = Field(default=594, ge=1, le=5000)
    origin_x: int | None = None
    origin_y: int | None = None
    horizontal_visibility: Literal["left", "right"] = "right"
    vertical_visibility: Literal["top", "bottom"] = "top"
    resize_windows: bool = True
    one_stack: bool = False
    show_window_on_arrange: bool = False
    show_window_on_resize: bool | None = None
    app_window: str | None = None


app = FastAPI(title="agent_charts_capture_worker", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _require_authorization(authorization: str | None) -> None:
    token = os.environ.get("CAPTURE_WORKER_TOKEN")
    if token:
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="unauthorized")


def _window_preview_base64(window_id: int) -> str:
    from io import BytesIO

    from PIL import Image

    from .window_capture import capture_window_png

    png = capture_window_png(window_id=window_id)
    img = Image.open(BytesIO(png)).convert("RGB")
    thumb = img.resize((180, 90), Image.Resampling.LANCZOS)
    out = BytesIO()
    thumb.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


def _fallback_preview_base64(*, title: str, reason: str) -> str:
    from io import BytesIO

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (180, 90), color=(18, 18, 18))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 179, 89), outline=(80, 80, 80), width=1)
    draw.text((6, 6), title[:30], fill=(246, 224, 94))
    draw.text((6, 44), reason[:38], fill=(190, 190, 190))
    out = BytesIO()
    img.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")

# replaced by _resize_windows_batch to process faster
def _set_window_position(
    *,
    owner_name: str,
    window_name: str,
    x: int,
    y: int,
    resize_window: bool,
    show_window: bool,
    width: int,
    height: int,
) -> bool:
    safe_owner = owner_name.replace('"', '\\"')
    safe_title = window_name.replace('"', '\\"')
    script = f'''
        set _owner to "{safe_owner}"
        set _title to "{safe_title}"
        set _x to {x}
        set _y to {y}
        set _resizeWindow to {str(resize_window).lower()}
        set _showWindow to {str(show_window).lower()}
        set _w to {width}
        set _h to {height}
        set _result to "not-found"

        if _showWindow then
            try
                tell application _owner to activate
            end try
        end if
        tell application "System Events"
            repeat with p in (every process whose background only is false)
                set _pname to (name of p) as text
                if (_pname is _owner) or (_pname contains _owner) then
                    try
                        repeat with w in (windows of p)
                            set _wname to ""
                            try
                                set _wname to (name of w) as text
                            end try
                            if (_wname is _title) or (_wname contains _title) then
                                if _resizeWindow then
                                    set size of w to {{_w, _h}}
                                end if
                                set position of w to {{_x, _y}}
                                if _showWindow then
                                    set frontmost of p to true
                                    try
                                        perform action "AXRaise" of w
                                    end try
                                end if
                                set _result to "moved"
                                exit repeat
                            end if
                        end repeat
                    end try
                end if
                if _result is not "not-found" then
                    exit repeat
                end if
            end repeat
        end tell
        return _result
    '''
    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    stdout = (proc.stdout or "").strip()
    return proc.returncode == 0 and stdout == "moved"


def _set_windows_positions_batch(*, requests: list[dict[str, Any]]) -> list[tuple[bool, bool]]:
    if not requests:
        return []

    script_lines = [
        "on _moveOne(_owner, _title, _x, _y, _resizeWindow, _showWindow, _w, _h)",
        '    set _result to "not-found"',
        "",
        "    if _showWindow then",
        "        try",
        "            tell application _owner to activate",
        "        end try",
        "    end if",
        '    tell application "System Events"',
        "        repeat with p in (every process whose background only is false)",
        '            set _pname to (name of p) as text',
        "            if (_pname is _owner) or (_pname contains _owner) then",
        "                try",
        "                    repeat with w in (windows of p)",
        '                        set _wname to ""',
        "                        try",
        '                            set _wname to (name of w) as text',
        "                        end try",
        "                        if (_wname is _title) or (_wname contains _title) then",
        "                            if _resizeWindow then",
        "                                set size of w to {_w, _h}",
        "                            end if",
        "                            set position of w to {_x, _y}",
        "                            if _showWindow then",
        "                                set frontmost of p to true",
        "                                try",
        '                                    perform action "AXRaise" of w',
        "                                end try",
        "                            end if",
        '                            set _result to "moved"',
        "                            exit repeat",
        "                        end if",
        "                    end repeat",
        "                end try",
        "            end if",
        '            if _result is not "not-found" then',
        "                exit repeat",
        "            end if",
        "        end repeat",
        "    end tell",
        "",
        "    return _result",
        "end _moveOne",
        "",
        'set _out to ""',
    ]

    for idx, req in enumerate(requests):
        safe_owner = str(req.get("owner_name") or "").replace('"', '\\"')
        safe_title = str(req.get("window_name") or "").replace('"', '\\"')
        x = int(req.get("x") or 0)
        y = int(req.get("y") or 0)
        resize_window = str(bool(req.get("resize_window"))).lower()
        show_window = str(bool(req.get("show_window"))).lower()
        width = int(req.get("width") or 0)
        height = int(req.get("height") or 0)
        allow_fallback_activation = str(bool(req.get("allow_fallback_activation"))).lower()

        script_lines.extend(
            [
                (
                    f'set _r{idx} to _moveOne("{safe_owner}", "{safe_title}", {x}, {y}, '
                    f'{resize_window}, {show_window}, {width}, {height})'
                ),
                f'set _fb{idx} to false',
                f'if (_r{idx} is not "moved") and ({allow_fallback_activation}) then',
                (
                    f'set _r{idx} to _moveOne("{safe_owner}", "{safe_title}", {x}, {y}, '
                    f'{resize_window}, true, {width}, {height})'
                ),
                f'if _r{idx} is "moved" then set _fb{idx} to true',
                "end if",
                f'set _out to _out & "{idx}:" & _r{idx} & ":" & (_fb{idx} as text) & linefeed',
            ]
        )

    script_lines.append("return _out")
    script = "\n".join(script_lines)

    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    stdout = (proc.stdout or "").strip()

    results: list[tuple[bool, bool]] = [(False, False)] * len(requests)
    for line in stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        idx_text, status, used_fallback_text = parts
        try:
            idx = int(idx_text)
        except ValueError:
            continue
        if not (0 <= idx < len(results)):
            continue
        moved = status.strip() == "moved"
        used_fallback_activation = used_fallback_text.strip().lower() == "true"
        results[idx] = (moved, used_fallback_activation)

    return results


def _resolve_arrange_app_window(explicit_app_window: str | None) -> str | None:
    app_window = (
        explicit_app_window
        or os.environ.get("CAPTURE_APP_WINDOW")
        or os.environ.get("IAWWAI_APP_WINDOW")
        or os.environ.get("APP_WINDOW")
    )
    if not app_window:
        return "Firefox"
    value = app_window.strip()
    if not value:
        return "Firefox"
    if value.lower() == "auto":
        return "Firefox"
    return value


def _activate_app_window(owner_name: str | None) -> bool:
    if not owner_name:
        return False
    safe_owner = owner_name.replace('"', '\\"')
    script = f'''
        set _owner to "{safe_owner}"
        set _result to "not-found"

        try
            tell application _owner to activate
            set _result to "activated"
        end try

        if _result is "not-found" then
            tell application "System Events"
                repeat with p in (every process whose background only is false)
                    set _pname to (name of p) as text
                    if (_pname is _owner) or (_pname contains _owner) then
                        set frontmost of p to true
                        set _result to "activated"
                        exit repeat
                    end if
                end repeat
            end tell
        end if

        return _result
    '''
    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    stdout = (proc.stdout or "").strip()
    return proc.returncode == 0 and stdout == "activated"


def _extract_timeframe_from_title(window_title: str) -> str | None:
    match = re.search(r"\s/\s(1m|3m|5m|15m|30m|45m|1h|2h|4h|1D|1W|1M)$", window_title.strip())
    if not match:
        return None
    return match.group(1)


def _filtered_tradingview_windows(owner_substr_override: str | None = None) -> list[Any]:
    owner_substr = (
        owner_substr_override
        or os.environ.get("TV_WINDOW_OWNER")
        or os.environ.get("TRADINGVIEW_WINDOW_OWNER")
        or "TradingView"
    )
    chart_title_re = re.compile(r"^.+\s/\s(1m|3m|5m|15m|30m|45m|1h|2h|4h|1D|1W|1M)$")

    from .window_capture import list_windows

    owner_substr_l = owner_substr.lower()
    windows = []
    for w in list_windows():
        if owner_substr_l not in w.owner_name.lower():
            continue
        title = (w.window_name or "").strip()
        if not title:
            continue
        if title == "TradingView":
            continue
        if not chart_title_re.match(title):
            continue
        windows.append(w)
    windows.sort(key=lambda w: (w.owner_name.lower(), w.window_name.lower(), w.window_id))
    return windows


@app.get("/tradingview/windows")
async def list_tradingview_windows(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_authorization(authorization)
    windows = _filtered_tradingview_windows()

    out: list[dict[str, Any]] = []
    for w in windows:
        preview_error: str | None = None
        try:
            preview_base64 = _window_preview_base64(w.window_id)
        except Exception as exc:
            preview_error = f"{type(exc).__name__}: {exc}"
            preview_base64 = _fallback_preview_base64(title=w.window_name, reason="preview unavailable")
        out.append(
            {
                "window_id": w.window_id,
                "owner_name": w.owner_name,
                "window_name": w.window_name,
                "bounds": w.bounds,
                "preview_png_base64": preview_base64,
                "preview_error": preview_error,
            }
        )
    return {"ok": True, "windows": out}


@app.post("/tradingview/windows/arrange")
async def arrange_tradingview_windows(
    body: ArrangeWindowsRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_authorization(authorization)
    if not body.placements:
        return {"ok": True, "arranged": 0, "details": []}

    filtered_windows = _filtered_tradingview_windows()
    filtered_by_id = {w.window_id: w for w in filtered_windows}
    filtered_by_key: dict[tuple[str, str], list[Any]] = {}
    for w in filtered_windows:
        filtered_by_key.setdefault((w.owner_name, w.window_name), []).append(w)

    matched_targets: list[tuple[ArrangePlacement, Any]] = []
    for placement in body.placements:
        matched = None
        if placement.window_id is not None:
            matched = filtered_by_id.get(placement.window_id)
        if matched is None:
            bucket = filtered_by_key.get((placement.owner_name, placement.window_name)) or []
            if bucket:
                matched = bucket[0]
        if matched is None:
            continue
        matched_targets.append((placement, matched))

    if not matched_targets:
        return {
            "ok": True,
            "arranged": 0,
            "requested": len(body.placements),
            "skipped": len(body.placements),
            "details": [],
        }

    matched_bounds = [target for _, target in matched_targets]
    # Keep current top-left anchor unless explicit origin is provided.
    if body.origin_x is None or body.origin_y is None:
        auto_origin_x = min((w.bounds.get("X", 0) for w in matched_bounds), default=0)
        auto_origin_y = min((w.bounds.get("Y", 0) for w in matched_bounds), default=0)
    else:
        auto_origin_x = body.origin_x
        auto_origin_y = body.origin_y

    details: list[dict[str, Any]] = []
    arranged = 0
    fallback_activations = 0

    show_window_on_arrange = body.show_window_on_arrange
    if body.show_window_on_resize is not None:
        show_window_on_arrange = bool(body.show_window_on_resize)

    tv_window_width_raw = os.environ.get("TV_WINDOW_WIDTH", "1738").strip()
    tv_window_height_raw = os.environ.get("TV_WINDOW_HEIGHT", "858").strip()
    try:
        tv_window_width = int(tv_window_width_raw)
    except ValueError:
        tv_window_width = 1738
    try:
        tv_window_height = int(tv_window_height_raw)
    except ValueError:
        tv_window_height = 858

    def _visibility_sort_key(target: tuple[ArrangePlacement, Any]) -> tuple[int, int]:
        placement, _ = target
        h_score = placement.col if body.horizontal_visibility == "right" else -placement.col
        v_score = -placement.row if body.vertical_visibility == "top" else placement.row
        return (v_score, h_score)

    if body.one_stack:
        ordered_targets = matched_targets
    else:
        # Move less-visible windows first and more-visible windows last.
        ordered_targets = sorted(matched_targets, key=_visibility_sort_key)

    move_requests: list[dict[str, Any]] = []
    move_meta: list[tuple[ArrangePlacement, Any, int, int]] = []

    for placement, matched_window in ordered_targets:
        if body.one_stack:
            x = int(auto_origin_x)
            y = int(auto_origin_y)
        else:
            x = int(auto_origin_x + (placement.col * body.step_x))
            y = int(auto_origin_y + (placement.row * body.step_y))
        move_requests.append(
            {
                "owner_name": matched_window.owner_name,
                "window_name": matched_window.window_name,
                "x": x,
                "y": y,
                "resize_window": body.resize_windows,
                "show_window": show_window_on_arrange,
                "width": tv_window_width,
                "height": tv_window_height,
                "allow_fallback_activation": not show_window_on_arrange,
            }
        )
        move_meta.append((placement, matched_window, x, y))

    move_results = _set_windows_positions_batch(requests=move_requests)

    for idx, (_placement, matched_window, x, y) in enumerate(move_meta):
        moved, used_fallback_activation = move_results[idx] if idx < len(move_results) else (False, False)
        if used_fallback_activation:
            fallback_activations += 1
        if moved:
            arranged += 1
        details.append(
            {
                "window_id": matched_window.window_id,
                "owner_name": matched_window.owner_name,
                "window_name": matched_window.window_name,
                "x": x,
                "y": y,
                "moved": moved,
                "resized": body.resize_windows,
                "used_fallback_activation": used_fallback_activation,
            }
        )

    app_window_name = _resolve_arrange_app_window(body.app_window)
    app_window_activated = False
    if show_window_on_arrange or fallback_activations > 0:
        app_window_activated = _activate_app_window(app_window_name)

    return {
        "ok": True,
        "arranged": arranged,
        "requested": len(body.placements),
        "skipped": len(body.placements) - len(matched_targets),
        "origin_x": auto_origin_x,
        "origin_y": auto_origin_y,
        "horizontal_visibility": body.horizontal_visibility,
        "vertical_visibility": body.vertical_visibility,
        "one_stack": body.one_stack,
        "resize_windows": body.resize_windows,
        "show_window_on_arrange": show_window_on_arrange,
        "fallback_activations": fallback_activations,
        "app_window": app_window_name,
        "app_window_activated": app_window_activated,
        "window_width": tv_window_width,
        "window_height": tv_window_height,
        "details": details,
    }


@app.post("/resize-windows-dismiss-tv-banner")
async def resize_windows_dismiss_tv_banner(
    body: ResizeWindowsDismissTVBannerRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_authorization(authorization)

    from .capture_and_upload import TIMEFRAMES_ORDER, resize_windows_dismiss_tv_banner_batch
    from .window_capture import find_window

    def _env_bool(name: str, default: bool) -> bool:
        v = os.environ.get(name)
        if v is None:
            return default
        return v.strip().lower() in {"1", "true", "yes", "on"}

    def _env_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def _env_float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    tv_resize_and_dismiss_banner = body.tv_resize_and_dismiss_banner
    if tv_resize_and_dismiss_banner is None:
        tv_resize_and_dismiss_banner = os.environ.get("TV_RESIZE_AND_DISMISS_BANNER", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    if tv_resize_and_dismiss_banner:
        tv_calibrate_window_size = True
        dismiss_tv_banner = True
    else:
        tv_calibrate_window_size = (
            body.tv_calibrate_window_size
            if body.tv_calibrate_window_size is not None
            else _env_bool("TV_CALIBRATE_WINDOW_SIZE", True)
        )
        dismiss_tv_banner = (
            body.dismiss_tv_banner
            if body.dismiss_tv_banner is not None
            else _env_bool("TV_DISMISS_BANNER", True)
        )

    if not tv_calibrate_window_size:
        return {
            "ok": True,
            "resized": 0,
            "requested": 0,
            "details": [],
            "skipped": "tv_calibrate_window_size is disabled",
        }

    show_tv_window_on_calibration = (
        body.show_tv_window_on_calibration
        if body.show_tv_window_on_calibration is not None
        else _env_bool("TV_SHOW_WINDOW_ON_CALIBRATION", True)
    )
    tv_window_width = body.tv_window_width or _env_int("TV_WINDOW_WIDTH", 1738)
    tv_window_height = body.tv_window_height or _env_int("TV_WINDOW_HEIGHT", 858)
    tv_window_resize_wait_seconds = (
        body.tv_window_resize_wait_seconds
        if body.tv_window_resize_wait_seconds is not None
        else _env_float("TV_WINDOW_RESIZE_WAIT_SECONDS", 0.35)
    )
    window_owner = (
        body.window_owner
        or os.environ.get("TV_WINDOW_OWNER")
        or os.environ.get("TRADINGVIEW_WINDOW_OWNER")
        or "TradingView"
    )
    title_tmpl = (
        body.window_title_template
        or os.environ.get("TV_WINDOW_TITLE_TEMPLATE")
        or os.environ.get("TRADINGVIEW_WINDOW_TITLE_TEMPLATE")
        or "{symbol} / {tf}"
    )
    debug = bool(body.debug_env)

    template_matching_requested = bool(body.window_title_template)
    template_matching_enabled = bool(body.window_title_template and body.symbol)
    available_windows = _filtered_tradingview_windows(owner_substr_override=window_owner)
    window_by_tf: dict[str, Any] = {}
    for w in available_windows:
        tf = _extract_timeframe_from_title((w.window_name or "").strip())
        if tf and tf not in window_by_tf:
            window_by_tf[tf] = w

    requests: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for tf in TIMEFRAMES_ORDER:
        tf_env = {
            "4h": "TV_TIMEFRAME_4H",
            "1h": "TV_TIMEFRAME_1H",
            "30m": "TV_TIMEFRAME_30M",
            "15m": "TV_TIMEFRAME_15M",
            "5m": "TV_TIMEFRAME_5M",
            "1m": "TV_TIMEFRAME_1M",
        }[tf]
        enabled = _env_bool(tf_env, True)
        if not enabled:
            details.append({"timeframe": tf, "enabled": False, "found": False, "resized": False})
            continue

        w = None
        title_sub = None
        if template_matching_enabled:
            title_sub = title_tmpl.format(symbol=body.symbol, tf=tf)
            try:
                w = find_window(owner_substr=window_owner, title_substr=title_sub)
            except Exception:
                w = None

        if w is None:
            w = window_by_tf.get(tf)

        if w is None:
            detail: dict[str, Any] = {
                "timeframe": tf,
                "enabled": True,
                "found": False,
                "resized": False,
                "error": (
                    f"No TradingView window found for timeframe {tf}. "
                    f"Open any window whose title ends with ' / {tf}'."
                ),
            }
            if template_matching_requested and not template_matching_enabled:
                detail["template_match_skipped"] = "window_title_template was provided but symbol is missing"
            details.append(detail)
            continue

        selected_title = (w.window_name or "").strip()

        requests.append(
            {
                "owner_substr": w.owner_name,
                "title_substr": selected_title,
                "window_id": w.window_id,
                "width": tv_window_width,
                "height": tv_window_height,
                "bring_to_front": show_tv_window_on_calibration,
                "app_owner_name": w.owner_name,
            }
        )
        details.append(
            {
                "timeframe": tf,
                "enabled": True,
                "found": True,
                "resized": False,
                "title": selected_title,
                "window_id": w.window_id,
            }
        )

    if not requests:
        return {
            "ok": True,
            "resized": 0,
            "requested": 0,
            "dismiss_tv_banner": dismiss_tv_banner,
            "details": details,
        }

    resize_results = resize_windows_dismiss_tv_banner_batch(
        requests=requests,
        dismiss_banner=dismiss_tv_banner,
        debug=debug,
    )
    if any(resize_results) and tv_window_resize_wait_seconds > 0:
        time.sleep(tv_window_resize_wait_seconds)

    resize_iter = iter(resize_results)
    for item in details:
        if item.get("found"):
            item["resized"] = bool(next(resize_iter, False))

    resized_count = sum(1 for item in details if item.get("resized"))
    return {
        "ok": True,
        "resized": resized_count,
        "requested": len(requests),
        "dismiss_tv_banner": dismiss_tv_banner,
        "details": details,
    }


@app.post("/trigger-capture")
async def trigger_capture(
    body: CaptureRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_authorization(authorization)

    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "mac" / "agent_charts_screen" / "capture_and_upload.py"
    layout_path = os.environ.get("CAPTURE_LAYOUT_PATH") or str(repo_root / "mac" / "agent_charts_screen" / "layout.json")
    base_url = os.environ.get("AGENT_CHARTS_SIGNAL_BASE_URL") or "http://127.0.0.1:8080"
    default_per_tf_windows = os.environ.get("CAPTURE_PER_TF_WINDOWS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    cmd = [
        sys.executable,
        str(script_path),
        "--layout",
        layout_path,
        "--symbol",
        body.symbol,
        "--case-id",
        body.case_id,
        "--base-url",
        base_url,
    ]

    if body.per_tf_windows is True or (body.per_tf_windows is None and default_per_tf_windows):
        cmd.append("--per-tf-windows")

    # Check combined setting first
    tv_resize_and_dismiss_banner = body.tv_resize_and_dismiss_banner
    if tv_resize_and_dismiss_banner is None:
        tv_resize_and_dismiss_banner = os.environ.get("TV_RESIZE_AND_DISMISS_BANNER", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    # If combined setting is enabled, override individual settings
    if tv_resize_and_dismiss_banner:
        tv_calibrate_window_size = True
        dismiss_tv_banner = True
        print(f"[worker_server] tv_resize_and_dismiss_banner=True (enables both resize and dismiss)")
    else:
        tv_calibrate_window_size = body.tv_calibrate_window_size
        if tv_calibrate_window_size is None:
            tv_calibrate_window_size = os.environ.get("TV_CALIBRATE_WINDOW_SIZE", "true").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        
        dismiss_tv_banner = body.dismiss_tv_banner
        if dismiss_tv_banner is None:
            dismiss_tv_banner = os.environ.get("TV_DISMISS_BANNER", "true").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }

    cmd.append("--tv-calibrate-window-size" if tv_calibrate_window_size else "--no-tv-calibrate-window-size")

    show_tv_window_on_calibration = body.show_tv_window_on_calibration
    if show_tv_window_on_calibration is None:
        show_tv_window_on_calibration = os.environ.get("TV_SHOW_WINDOW_ON_CALIBRATION", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    cmd.append("--show-tv-window-on-calibration" if show_tv_window_on_calibration else "--no-show-tv-window-on-calibration")

    # dismiss_tv_banner = body.dismiss_tv_banner
    # if dismiss_tv_banner is None:
    #     dismiss_tv_banner = os.environ.get("TV_DISMISS_BANNER", "true").strip().lower() in {
    #         "1",
    #         "true",
    #         "yes",
    #         "on",
    #     }
    cmd.append("--dismiss-tv-banner" if dismiss_tv_banner else "--no-dismiss-tv-banner")
    print(f"[worker_server] dismiss_tv_banner={dismiss_tv_banner}")

    if body.provider:
        cmd.extend(["--vision-provider", body.provider])

    if body.vision_model_pass1:
        cmd.extend(["--vision-model-pass1", body.vision_model_pass1])
    if body.vision_model_pass2:
        cmd.extend(["--vision-model-pass2", body.vision_model_pass2])

    if body.include_liquidation_heatmap:
        cmd.append("--include-liquidation-heatmap")

        liquidation_owner = (
            body.liquidation_heatmap_window_owner
            or os.environ.get("LIQUIDATION_HEATMAP_WINDOW_OWNER")
            or os.environ.get("CG_WINDOW_OWNER")
        )
        if liquidation_owner:
            cmd.extend(["--liquidation-heatmap-window-owner", liquidation_owner])

        liquidation_title = (
            body.liquidation_heatmap_window_title
            or os.environ.get("LIQUIDATION_HEATMAP_WINDOW_TITLE")
            or os.environ.get("CG_WINDOW_TITLE")
            or "Liquidation Heatmap"
        )
        cmd.extend(["--liquidation-heatmap-window-title", liquidation_title])

        refresh_wait = body.liquidation_heatmap_refresh_wait_seconds
        if refresh_wait is None:
            refresh_wait_raw = os.environ.get("LIQUIDATION_HEATMAP_REFRESH_WAIT_SECONDS")
            if refresh_wait_raw:
                try:
                    refresh_wait = float(refresh_wait_raw)
                except ValueError:
                    refresh_wait = None
        if refresh_wait is not None:
            cmd.extend(["--liquidation-heatmap-refresh-wait-seconds", str(refresh_wait)])

    if body.liquidation_heatmap_time_horizon_hours is not None:
        cmd.extend(
            [
                "--liquidation-heatmap-time-horizon-hours",
                str(body.liquidation_heatmap_time_horizon_hours),
            ]
        )

    http_timeout_seconds = body.http_timeout_seconds
    if http_timeout_seconds is None:
        timeout_raw = os.environ.get("CAPTURE_HTTP_TIMEOUT_SECONDS")
        if timeout_raw:
            try:
                http_timeout_seconds = float(timeout_raw)
            except ValueError:
                http_timeout_seconds = None
    if http_timeout_seconds is None:
        http_timeout_seconds = 300.0
    cmd.extend(["--http-timeout-seconds", str(http_timeout_seconds)])

    app_window = (
        body.app_window
        or os.environ.get("CAPTURE_APP_WINDOW")
        or os.environ.get("IAWWAI_APP_WINDOW")
        or os.environ.get("APP_WINDOW")
    )
    if not app_window or app_window.strip().lower() == "windsurf":
        app_window = "Firefox"
    cmd.extend(["--app-window", app_window])

    enable_debug_env = body.debug_env
    if enable_debug_env is None:
        enable_debug_env = os.environ.get("CAPTURE_DEBUG_ENV", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    # Auto-enable debug when banner dismissal is active to see logs
    if enable_debug_env or dismiss_tv_banner:
        cmd.append("--debug-env")
        if dismiss_tv_banner:
            print(f"[worker_server] Auto-enabled --debug-env for banner dismissal logging")

    worker_log_path = Path(os.environ.get("CAPTURE_WORKER_LOG_PATH") or (repo_root / "mac" / "agent_charts_screen" / "worker_capture.log"))
    worker_log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = worker_log_path.open("ab")

    print(f"[worker_server] Starting capture for case_id={body.case_id}")
    print(f"[worker_server] Logs will be written to: {worker_log_path}")
    print(f"[worker_server] To monitor: tail -f {worker_log_path}")

    # Run detached so Cloud Run can return quickly while capture+analyze continues.
    subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    return {
        "ok": True,
        "accepted": True,
        "case_id": body.case_id,
        "worker_log_path": str(worker_log_path),
        "command": cmd,
    }
