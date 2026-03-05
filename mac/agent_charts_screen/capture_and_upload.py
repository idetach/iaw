from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import os
import subprocess
import time

try:
    import httpx
except ModuleNotFoundError as e:  # pragma: no cover
    raise SystemExit(
        "Missing dependency 'httpx' for the current Python interpreter.\n"
        "Install using:\n\n"
        "  python -m pip install -r mac/agent_charts_screen/requirements.txt\n"
    ) from e

try:
    import mss
except ModuleNotFoundError as e:  # pragma: no cover
    raise SystemExit(
        "Missing dependency 'mss' for the current Python interpreter.\n"
        "Install using the SAME python you are running, e.g.:\n\n"
        "  python -m pip install -r mac/agent_charts_screen/requirements.txt\n"
    ) from e

try:
    from PIL import Image
except ModuleNotFoundError as e:  # pragma: no cover
    raise SystemExit(
        "Missing dependency 'Pillow' for the current Python interpreter.\n"
        "Install using:\n\n"
        "  python -m pip install -r mac/agent_charts_screen/requirements.txt\n"
    ) from e

from dotenv import load_dotenv


TIMEFRAMES_ORDER = ["4h", "1h", "30m", "15m", "5m", "1m"]
OUT_W = 1308
OUT_H = 768
LIQUIDATION_HEATMAP_OUT_H = 786


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    s = v.strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _env_int(name: str) -> int | None:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _env_float(name: str) -> float | None:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _placeholder_png(*, tf: str, reason: str) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (OUT_W, OUT_H), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    txt = f"{tf} unavailable\n{reason}"[:500]
    draw.text((20, 20), txt, fill=(235, 235, 235))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _crop_rect_from_image(img: Image.Image, *, x: int, y: int, w: int, h: int) -> Image.Image:
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise SystemExit("Invalid crop rect")
    if x + w > img.width or y + h > img.height:
        raise SystemExit(
            f"Crop rect out of bounds. Image is {img.width}x{img.height}, rect is x={x},y={y},w={w},h={h}"
        )
    return img.crop((x, y, x + w, y + h))


def capture_monitor(monitor_index: int) -> Image.Image:
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        return img


def crop_resize_png(img: Image.Image, rect: dict, out_w: int, out_h: int) -> bytes:
    x, y, w, h = int(rect["x"]), int(rect["y"]), int(rect["w"]), int(rect["h"])
    cropped = img.crop((x, y, x + w, y + h))
    resized = cropped.resize((out_w, out_h), Image.Resampling.LANCZOS)
    from io import BytesIO

    buf = BytesIO()
    resized.save(buf, format="PNG")
    return buf.getvalue()


def _refresh_safari_tab(*, title_substr: str, wait_seconds: float, debug: bool = False) -> None:
    safe_title_substr = title_substr.replace('"', '\\"')
    script = f'''
        set _matched to false
        tell application "Safari"
            activate
            repeat with w in windows
                repeat with t in tabs of w
                    set _tabName to ""
                    set _tabURL to ""
                    try
                        set _tabName to (name of t) as text
                    end try
                    try
                        set _tabURL to (URL of t) as text
                    end try

                    if (_tabName contains "{safe_title_substr}") or (_tabURL contains "coinglass.com") then
                        set current tab of w to t
                        set index of w to 1
                        set _matched to true
                        exit repeat
                    end if
                end repeat
                if _matched then
                    exit repeat
                end if
            end repeat
        end tell

        if _matched then
            tell application "System Events"
                keystroke "r" using command down
            end tell
            return "refreshed-via-cmd-r"
        end if

        return "tab-not-found"
    '''
    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    if debug:
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        print(f"liquidation_heatmap refresh result: returncode={proc.returncode}, stdout={stdout!r}, stderr={stderr!r}")
    time.sleep(wait_seconds)


def _dismiss_tradingview_banner(
    *,
    owner_name: str,
    window_name: str,
    window_id: int,
    move_cursor_after_click: bool = False,
    debug: bool = False,
) -> bool:
    """Attempt to dismiss TradingView 'Restore connection' banner by clicking at fixed position."""
    safe_owner = owner_name.replace('"', '\\"')
    safe_window = window_name.replace('"', '\\"')

    try:
        from .window_capture import get_window_scale_factor
    except ImportError:
        from window_capture import get_window_scale_factor
    
    # Detect actual scale factor for this window
    scale_factor = get_window_scale_factor(window_id=window_id)
    
    # Banner button position relative to window top-left: x=750, y=700 (physical pixels)
    # AppleScript returns logical pixels, but pyautogui uses physical pixels on Retina
    # So we need to multiply AppleScript coords by scale_factor and add physical pixel offsets
    click_x_physical = 750  # Physical pixels from measurement
    click_y_physical = 700  # Physical pixels from measurement
    
    # First, get window position using AppleScript
    script = f'''
        set _owner to "{safe_owner}"
        set _window to "{safe_window}"

        tell application _owner to activate
        delay 1.0

        tell application "System Events"
            tell process _owner
                try
                    set _targetWindow to missing value
                    try
                        set _targetWindow to (first window whose name is _window)
                    end try
                    if _targetWindow is missing value then
                        set _targetWindow to (first window whose name contains _window)
                    end if
                    
                    -- Bring this specific window to front
                    perform action "AXRaise" of _targetWindow
                    delay 0.3
                    
                    set _winPos to position of _targetWindow
                    set _winX to item 1 of _winPos
                    set _winY to item 2 of _winPos
                    
                    return (_winX as text) & "," & (_winY as text)
                on error errMsg
                    return "error:" & errMsg
                end try
            end tell
        end tell
    '''
    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    stdout = (proc.stdout or "").strip()
    
    if stdout.startswith("error:"):
        print(f"[banner_dismiss] window={window_name!r}, owner={owner_name!r}\n[banner_dismiss] {stdout}")
        return False
    
    try:
        win_x_logical, win_y_logical = map(int, stdout.split(","))
        if debug:
            print(f"[banner_dismiss] window position: logical=({win_x_logical},{win_y_logical}), scale_factor={scale_factor}")
        # Convert AppleScript logical pixels to physical pixels (multiply by scale_factor)
        win_x_physical = int(win_x_logical * scale_factor)
        win_y_physical = int(win_y_logical * scale_factor)
        # Add physical pixel offsets
        abs_x = click_x_physical + win_x_physical
        abs_y = click_y_physical + win_y_physical
    except (ValueError, AttributeError):
        print(f"[banner_dismiss] window={window_name!r}, failed to parse position: {stdout!r}")
        return False
    
    # Now use pyautogui to click at the absolute screen coordinates
    try:
        import pyautogui
        # Move mouse to position first for visual feedback (duration makes it visible)
        print(
            f"[banner_dismiss] window={window_name!r}, owner={owner_name!r}\n"
            f"[banner_dismiss] moving mouse to physical coords ({abs_x},{abs_y}) = window_logical({win_x_logical},{win_y_logical})*{scale_factor} + offset({click_x_physical},{click_y_physical})"
        )
        pyautogui.moveTo(abs_x, abs_y, duration=0.3)
        time.sleep(0.5)
        
        # Perform the click
        print(f"[banner_dismiss] clicking at ({abs_x},{abs_y})")
        pyautogui.click()
        
        # Wait after click for banner to dismiss
        time.sleep(1.0)

        if move_cursor_after_click:
            park_x = win_x_physical + 20
            park_y = win_y_physical + 20
            pyautogui.moveTo(park_x, park_y, duration=0.2)
            if debug:
                print(
                    f"[banner_dismiss] moved cursor away to window top-left area ({park_x},{park_y}) "
                    f"for {window_name!r}"
                )

        print(f"[banner_dismiss] click completed for {window_name!r}")
        return True
    except ImportError:
        print(f"[banner_dismiss] pyautogui not installed, trying fallback")
        # Fallback: use osascript with do shell script and cliclick
        click_cmd = f'cliclick c:{abs_x},{abs_y}'
        proc = subprocess.run(["sh", "-c", click_cmd], check=False, capture_output=True, text=True)
        if proc.returncode == 0:
            print(
                f"[banner_dismiss] window={window_name!r}, owner={owner_name!r}\n"
                f"[banner_dismiss] clicked via cliclick at ({abs_x},{abs_y})"
            )
            return True
        else:
            print(
                f"[banner_dismiss] window={window_name!r}, owner={owner_name!r}\n"
                f"[banner_dismiss] cliclick failed: {proc.stderr}"
            )
            return False
    except Exception as e:
        print(f"[banner_dismiss] window={window_name!r}, click failed: {e}")
        return False


def _focus_app_window(*, app_window_substr: str, debug: bool = False) -> None:
    safe_app_window_substr = app_window_substr.replace('"', '\\"')
    script = f'''
        set _target to "{safe_app_window_substr}"
        set _result to "not-found"

        try
            tell application _target to activate
            return "activated-by-app-name"
        on error
        end try

        tell application "System Events"
            repeat with p in (every process whose background only is false)
                set _pname to (name of p) as text
                if _pname contains _target then
                    set frontmost of p to true
                    set _result to "activated-by-process-name"
                    exit repeat
                end if

                try
                    repeat with w in (windows of p)
                        if ((name of w) as text) contains _target then
                            set frontmost of p to true
                            try
                                perform action "AXRaise" of w
                            end try
                            set _result to "activated-by-window-title"
                            exit repeat
                        end if
                    end repeat
                end try

                if _result is not "not-found" then
                    exit repeat
                end if
            end repeat
        end tell

        return _result
    '''
    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    if debug:
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        print(f"app focus result: returncode={proc.returncode}, stdout={stdout!r}, stderr={stderr!r}")

#replaced by _resize_windows_batch to process faster
def _resize_window(
    *,
    owner_substr: str,
    title_substr: str,
    width: int,
    height: int,
    bring_to_front: bool,
    app_owner_name: str | None = None,
    debug: bool = False,
) -> bool:
    safe_owner = owner_substr.replace('"', '\\"')
    safe_title = title_substr.replace('"', '\\"')
    safe_app_owner = (app_owner_name or "").replace('"', '\\"')
    script = f'''
        set _owner to "{safe_owner}"
        set _title to "{safe_title}"
        set _appOwner to "{safe_app_owner}"
        set _w to {width}
        set _h to {height}
        set _result to "not-found"

        if {str(bring_to_front).lower()} and (_appOwner is not "") then
            try
                tell application _appOwner to activate
            end try
        end if

        tell application "System Events"
            repeat with p in (every process whose background only is false)
                set _pname to (name of p) as text
                if _pname contains _owner then
                    try
                        repeat with w in (windows of p)
                            set _wname to ""
                            try
                                set _wname to (name of w) as text
                            end try
                            if _wname contains _title then
                                set _currentSize to size of w
                                set _currentW to item 1 of _currentSize
                                set _currentH to item 2 of _currentSize
                                if (_currentW is _w) and (_currentH is _h) then
                                    if {str(bring_to_front).lower()} then
                                        set frontmost of p to true
                                        try
                                            perform action "AXRaise" of w
                                        end try
                                    end if
                                    set _result to "already-sized"
                                else
                                    set size of w to {{_w, _h}}
                                    if {str(bring_to_front).lower()} then
                                        set frontmost of p to true
                                        try
                                            perform action "AXRaise" of w
                                        end try
                                    end if
                                    set _result to "resized"
                                end if
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
    stderr = (proc.stderr or "").strip()
    if debug:
        print(
            "window resize result: "
            f"owner={owner_substr!r}, title={title_substr!r}, target={width}x{height}, "
            f"returncode={proc.returncode}, stdout={stdout!r}, stderr={stderr!r}"
        )
    return stdout == "resized"


def _resize_windows_batch(*, requests: list[dict[str, object]], debug: bool = False) -> list[bool]:
    if not requests:
        return []

    script_lines = [
        "on _resizeOne(_owner, _title, _appOwner, _w, _h, _bringFront)",
        '    set _result to "not-found"',
        "",
        '    if _bringFront and (_appOwner is not "") then',
        "        try",
        "            tell application _appOwner to activate",
        "        end try",
        "    end if",
        "",
        '    tell application "System Events"',
        "        repeat with p in (every process whose background only is false)",
        '            set _pname to (name of p) as text',
        "            if _pname contains _owner then",
        "                try",
        "                    repeat with w in (windows of p)",
        '                        set _wname to ""',
        "                        try",
        '                            set _wname to (name of w) as text',
        "                        end try",
        "                        if _wname contains _title then",
        "                            set _currentSize to size of w",
        "                            set _currentW to item 1 of _currentSize",
        "                            set _currentH to item 2 of _currentSize",
        "                            if (_currentW is _w) and (_currentH is _h) then",
        "                                if _bringFront then",
        "                                    set frontmost of p to true",
        "                                    try",
        '                                        perform action "AXRaise" of w',
        "                                    end try",
        "                                end if",
        '                                set _result to "already-sized"',
        "                            else",
        "                                set size of w to {_w, _h}",
        "                                if _bringFront then",
        "                                    set frontmost of p to true",
        "                                    try",
        '                                        perform action "AXRaise" of w',
        "                                    end try",
        "                                end if",
        '                                set _result to "resized"',
        "                            end if",
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
        "end _resizeOne",
        "",
        'set _out to ""',
    ]

    for idx, req in enumerate(requests):
        safe_owner = str(req.get("owner_substr") or "").replace('"', '\\"')
        safe_title = str(req.get("title_substr") or "").replace('"', '\\"')
        safe_app_owner = str(req.get("app_owner_name") or "").replace('"', '\\"')
        width = int(req.get("width") or 0)
        height = int(req.get("height") or 0)
        bring_to_front = str(bool(req.get("bring_to_front"))).lower()
        allow_fallback_activation = str(bool(req.get("allow_fallback_activation"))).lower()

        script_lines.extend(
            [
                (
                    f'set _r{idx} to _resizeOne("{safe_owner}", "{safe_title}", '
                    f'"{safe_app_owner}", {width}, {height}, {bring_to_front})'
                ),
                f'if (_r{idx} is not "resized") and ({allow_fallback_activation}) then',
                (
                    f'set _r{idx} to _resizeOne("{safe_owner}", "{safe_title}", '
                    f'"{safe_app_owner}", {width}, {height}, true)'
                ),
                "end if",
                f'set _out to _out & "{idx}:" & _r{idx} & linefeed',
            ]
        )

    script_lines.append("return _out")
    script = "\n".join(script_lines)

    proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if debug:
        print(
            "window batch resize result: "
            f"count={len(requests)}, returncode={proc.returncode}, stdout={stdout!r}, stderr={stderr!r}"
        )

    out = [False] * len(requests)
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        idx_text, status = line.split(":", 1)
        try:
            idx = int(idx_text)
        except ValueError:
            continue
        if 0 <= idx < len(out):
            out[idx] = status.strip() == "resized"
    return out


def resize_windows_dismiss_tv_banner_batch(
    *,
    requests: list[dict[str, object]],
    dismiss_banner: bool = True,
    debug: bool = False,
) -> list[bool]:
    """
    Combined function to resize windows and dismiss TradingView banners in one pass.
    Uses pyautogui for faster operations compared to AppleScript batch processing.
    
    Each request dict should contain:
    - owner_substr: str - window owner substring (e.g., "TradingView")
    - title_substr: str - window title substring (e.g., "BTCUSDT / 4h")
    - window_id: int - window ID for scale factor detection
    - width: int - target width in logical pixels
    - height: int - target height in logical pixels
    - bring_to_front: bool - whether to bring window to front
    - app_owner_name: str - application name for activation
    
    Returns list of bools indicating success for each request.
    """
    if not requests:
        return []

    try:
        from .window_capture import get_window_scale_factor
    except ImportError:
        from window_capture import get_window_scale_factor
    
    try:
        import pyautogui
    except ImportError:
        print("[resize_dismiss_batch] pyautogui not available, falling back to separate operations")
        return [False] * len(requests)
    
    results = []
    
    for idx, req in enumerate(requests):
        owner_substr = str(req.get("owner_substr") or "")
        title_substr = str(req.get("title_substr") or "")
        window_id = int(req.get("window_id") or 0)
        width = int(req.get("width") or 0)
        height = int(req.get("height") or 0)
        bring_to_front = bool(req.get("bring_to_front"))
        app_owner_name = str(req.get("app_owner_name") or "")
        
        safe_owner = owner_substr.replace('"', '\\"')
        safe_title = title_substr.replace('"', '\\"')
        safe_app = app_owner_name.replace('"', '\\"')
        
        is_last = (idx == len(requests) - 1)
        
        # Step 1: Activate app and get window, resize it, raise to front
        script = f'''
            set _owner to "{safe_owner}"
            set _title to "{safe_title}"
            set _w to {width}
            set _h to {height}
            set _bringFront to {"true" if bring_to_front else "false"}
            set _result to "not-found"
            
            tell application _owner to activate
            delay 1.0
            
            tell application "System Events"
                tell process _owner
                    try
                        set _targetWindow to missing value
                        try
                            set _targetWindow to (first window whose name is _title)
                        end try
                        if _targetWindow is missing value then
                            set _targetWindow to (first window whose name contains _title)
                        end if
                        
                        -- Resize window
                        set size of _targetWindow to {{_w, _h}}
                        
                    
                        -- Bring this specific window to front
                        perform action "AXRaise" of _targetWindow
                        delay 0.3
                        
                        -- Get window position for banner click
                        set _winPos to position of _targetWindow
                        set _winX to item 1 of _winPos
                        set _winY to item 2 of _winPos
                        
                        set _result to "resized:" & (_winX as text) & "," & (_winY as text)
                    on error errMsg
                        set _result to "error:" & errMsg
                    end try
                end tell
            end tell
            
            return _result
        '''
        
        proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
        stdout = (proc.stdout or "").strip()
        
        if debug:
            print(f"[resize_dismiss_batch] {idx}: {title_substr!r} -> {stdout!r}")
        
        # Parse result
        if not stdout.startswith("resized:"):
            results.append(False)
            continue
        
        # Extract window position
        try:
            pos_str = stdout.split(":", 1)[1]
            win_x_logical, win_y_logical = map(int, pos_str.split(","))
        except (ValueError, IndexError):
            results.append(False)
            continue
        
        # Step 2: Dismiss banner if requested
        if dismiss_banner:
            scale_factor = get_window_scale_factor(window_id=window_id)
            
            # Banner button position (physical pixels)
            click_x_physical = 750
            click_y_physical = 700
            
            # Convert to physical pixels and calculate absolute position
            win_x_physical = int(win_x_logical * scale_factor)
            win_y_physical = int(win_y_logical * scale_factor)
            abs_x = click_x_physical + win_x_physical
            abs_y = click_y_physical + win_y_physical
            
            if debug:
                print(
                    f"[resize_dismiss_batch] {idx}: banner click at ({abs_x},{abs_y}) = "
                    f"window_logical({win_x_logical},{win_y_logical})*{scale_factor} + offset({click_x_physical},{click_y_physical})"
                )
            
            # Move and click
            pyautogui.moveTo(abs_x, abs_y, duration=0.3)
            time.sleep(0.5)
            pyautogui.click()
            time.sleep(1.0)
            
            # Move cursor away on last window
            if is_last:
                park_x = win_x_physical + 20
                park_y = win_y_physical + 20
                pyautogui.moveTo(park_x, park_y, duration=0.2)
                if debug:
                    print(f"[resize_dismiss_batch] {idx}: moved cursor to ({park_x},{park_y})")
        
        results.append(True)
    
    if debug:
        success_count = sum(results)
        print(f"[resize_dismiss_batch] completed: {success_count}/{len(requests)} successful")
    
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument(
        "--case-id",
        type=str,
        default=None,
        help="Use an existing case ID (expects backend support for /v1/cases/{case_id}/upload-urls).",
    )
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--window-owner", type=str, default=None, help="Override layout window owner substring (e.g. TradingView)")
    parser.add_argument("--window-title", type=str, default=None, help="Override layout window title substring")
    parser.add_argument("--tv-window-width", type=int, default=None)
    parser.add_argument("--tv-window-height", type=int, default=None)
    parser.add_argument("--tv-window-resize-wait-seconds", type=float, default=None)
    parser.add_argument("--tv-calibrate-window-size", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--show-tv-window-on-calibration", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--dismiss-tv-banner", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument(
        "--per-tf-windows",
        action="store_true",
        help="Capture one window per timeframe (e.g. BTCUSDT / 4h) and apply a fixed crop.",
    )
    parser.add_argument(
        "--window-title-template",
        type=str,
        default=None,
        help="Template for per-timeframe window title substrings. Example: '{symbol} / {tf}'.",
    )
    parser.add_argument("--crop-x", type=int, default=None)
    parser.add_argument("--crop-y", type=int, default=None)
    parser.add_argument("--crop-w", type=int, default=None)
    parser.add_argument("--crop-h", type=int, default=None)
    parser.add_argument(
        "--vision-provider",
        choices=["claude", "openai", "gemini"],
        default=None,
        help="Override vision provider for this analyze call (defaults to server VISION_PROVIDER env).",
    )
    parser.add_argument(
        "--vision-model-pass1",
        type=str,
        default=None,
        help="Override pass1 model for this analyze call.",
    )
    parser.add_argument(
        "--vision-model-pass2",
        type=str,
        default=None,
        help="Override pass2 model for this analyze call.",
    )
    parser.add_argument(
        "--include-liquidation-heatmap",
        action="store_true",
        help="Capture and upload liquidation heatmap image and enable separate liquidation_heatmap LLM pass.",
    )
    parser.add_argument("--liquidation-heatmap-window-owner", type=str, default=None)
    parser.add_argument("--liquidation-heatmap-window-title", type=str, default="coinglass")
    parser.add_argument("--liquidation-heatmap-crop-x", type=int, default=None)
    parser.add_argument("--liquidation-heatmap-crop-y", type=int, default=None)
    parser.add_argument("--liquidation-heatmap-crop-w", type=int, default=None)
    parser.add_argument("--liquidation-heatmap-crop-h", type=int, default=None)
    parser.add_argument("--liquidation-heatmap-refresh-wait-seconds", type=float, default=5.0)
    parser.add_argument("--liquidation-heatmap-time-horizon-hours", type=int, default=None)
    parser.add_argument(
        "--http-timeout-seconds",
        type=float,
        default=180.0,
        help="HTTP timeout for create/upload/analyze requests (increase for slower LLM runs).",
    )
    parser.add_argument(
        "--app-window",
        type=str,
        default=None,
        help="App/process/window substring to bring back to front after liquidation heatmap capture (defaults to APP_WINDOW env).",
    )
    parser.add_argument("--debug-env", action="store_true")
    args = parser.parse_args()

    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

    base_url = args.base_url or (  # env-first behavior without adding extra deps
        __import__("os").environ.get("AGENT_CHARTS_SIGNAL_BASE_URL") or "http://127.0.0.1:8080"
    )

    layout: dict | None = None
    if args.layout:
        try:
            layout_text = args.layout.read_text(encoding="utf-8")
            layout = json.loads(layout_text)
        except FileNotFoundError:
            layout = None

    if args.per_tf_windows:
        window_owner = (
            args.window_owner
            or (layout or {}).get("window_owner")
            or os.environ.get("TV_WINDOW_OWNER")
            or os.environ.get("TRADINGVIEW_WINDOW_OWNER")
            or "TradingView"
        )
        title_tmpl = (
            args.window_title_template
            or (layout or {}).get("window_title_template")
            or os.environ.get("TV_WINDOW_TITLE_TEMPLATE")
            or os.environ.get("TRADINGVIEW_WINDOW_TITLE_TEMPLATE")
            or "{symbol} / {tf}"
        )

        crop_cfg = (layout or {}).get("crop") or {}

        cx = (
            args.crop_x
            if args.crop_x is not None
            else int(crop_cfg.get("x") or (_env_int("TV_CROP_X") or 55))
        )
        cy = (
            args.crop_y
            if args.crop_y is not None
            else int(crop_cfg.get("y") or (_env_int("TV_CROP_Y") or 114))
        )
        cw = (
            args.crop_w
            if args.crop_w is not None
            else int(crop_cfg.get("w") or (_env_int("TV_CROP_W") or OUT_W))
        )
        ch = (
            args.crop_h
            if args.crop_h is not None
            else int(crop_cfg.get("h") or (_env_int("TV_CROP_H") or OUT_H))
        )

        from window_capture import capture_window_png, find_window, get_window_scale_factor

        tv_window_width = args.tv_window_width or _env_int("TV_WINDOW_WIDTH") or 1738
        tv_window_height = args.tv_window_height or _env_int("TV_WINDOW_HEIGHT") or 858
        tv_window_resize_wait_seconds = (
            args.tv_window_resize_wait_seconds
            if args.tv_window_resize_wait_seconds is not None
            else (_env_float("TV_WINDOW_RESIZE_WAIT_SECONDS") or 0.35)
        )
        tv_calibrate_window_size = (
            args.tv_calibrate_window_size
            if args.tv_calibrate_window_size is not None
            else _env_bool("TV_CALIBRATE_WINDOW_SIZE", True)
        )
        show_tv_window_on_calibration = (
            args.show_tv_window_on_calibration
            if args.show_tv_window_on_calibration is not None
            else _env_bool("TV_SHOW_WINDOW_ON_CALIBRATION", True)
        )
        dismiss_tv_banner = (
            args.dismiss_tv_banner
            if args.dismiss_tv_banner is not None
            else _env_bool("TV_DISMISS_BANNER", True)
        )

        pngs_by_tf: dict[str, bytes] = {}
        if args.debug_env:
            print(f"per-tf mode: window_owner={window_owner!r}")
            print(f"per-tf mode: title_template={title_tmpl!r}")
            print(f"per-tf mode: crop x,y,w,h = {cx},{cy},{cw},{ch} (logical pixels)")
        
        # Detect Retina scaling from first enabled window
        scale_factor: float | None = None
        capture_targets: list[tuple[str, str, object]] = []
        
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
            if args.debug_env:
                print(f"{tf}: {tf_env}={os.environ.get(tf_env)!r} -> enabled={enabled}")
            if not enabled:
                pngs_by_tf[tf] = _placeholder_png(tf=tf, reason=f"disabled by {tf_env}=false")
                continue

            title_sub = title_tmpl.format(symbol=args.symbol, tf=tf)
            try:
                w = find_window(owner_substr=window_owner, title_substr=title_sub)
            except Exception as e:
                raise SystemExit(
                    "Failed to find TradingView window for timeframe.\n"
                    f"timeframe={tf!r}, expected title substring={title_sub!r}, owner substring={window_owner!r}.\n\n"
                    "Ensure this timeframe window is open (or disable it via TV_TIMEFRAME_*).\n"
                    "Example titles: 'BTCUSDT / 4h', 'BTCUSDT / 1h', 'BTCUSDT / 30m', 'BTCUSDT / 15m', 'BTCUSDT / 5m', 'BTCUSDT / 1m'.\n"
                    "Tip: run `python mac/agent_charts_screen/list_windows.py` to see visible window titles.\n\n"
                    f"Details: {e}"
                ) from e
            capture_targets.append((tf, title_sub, w))

        if tv_calibrate_window_size and tv_window_width > 0 and tv_window_height > 0 and capture_targets:
            # Use combined resize + banner dismiss function for better performance
            resize_results = resize_windows_dismiss_tv_banner_batch(
                requests=[
                    {
                        "owner_substr": window_owner,
                        "title_substr": title_sub,
                        "window_id": w.window_id,
                        "width": tv_window_width,
                        "height": tv_window_height,
                        "bring_to_front": show_tv_window_on_calibration,
                        "app_owner_name": w.owner_name,
                    }
                    for _, title_sub, w in capture_targets
                ],
                dismiss_banner=dismiss_tv_banner,
                debug=args.debug_env,
            )
            if any(resize_results) and tv_window_resize_wait_seconds > 0:
                time.sleep(tv_window_resize_wait_seconds)

        # # instead resize and dismiss in one go with resize_windows_dismiss_tv_banner_batch
        # if tv_calibrate_window_size and tv_window_width > 0 and tv_window_height > 0 and capture_targets:
        #     resize_results = _resize_windows_batch(
        #         requests=[
        #             {
        #                 "owner_substr": window_owner,
        #                 "title_substr": title_sub,
        #                 "width": tv_window_width,
        #                 "height": tv_window_height,
        #                 "bring_to_front": show_tv_window_on_calibration,
        #                 "app_owner_name": w.owner_name,
        #                 "allow_fallback_activation": not show_tv_window_on_calibration,
        #             }
        #             for _, title_sub, w in capture_targets
        #         ],
        #         debug=args.debug_env,
        #     )
        #     if any(resize_results) and tv_window_resize_wait_seconds > 0:
        #         time.sleep(tv_window_resize_wait_seconds)

        # # instead resize and dismiss in one go with resize_windows_dismiss_tv_banner_batch
        # # Dismiss TradingView banners before resize/capture 
        # if dismiss_tv_banner and capture_targets:
        #     last_target_index = len(capture_targets) - 1
        #     for idx, (tf, title_sub, w) in enumerate(capture_targets):
        #         dismissed = _dismiss_tradingview_banner(
        #             owner_name=w.owner_name,
        #             window_name=w.window_name,
        #             window_id=w.window_id,
        #             move_cursor_after_click=(idx == last_target_index),
        #             debug=args.debug_env,
        #         )
        #         if dismissed and args.debug_env:
        #             print(f"{tf}: dismissed TradingView banner")
        #     # Brief wait after dismissing banners
        #     time.sleep(0.5)

        for tf, title_sub, w in capture_targets:
            # Detect Retina scaling on first window
            if scale_factor is None:
                scale_factor = get_window_scale_factor(window_id=w.window_id)
                if args.debug_env:
                    print(f"Detected display scale factor: {scale_factor}x")
                    if scale_factor > 1.0:
                        print(f"  Scaling crop coords: ({cx},{cy},{cw},{ch}) -> ({int(cx*scale_factor)},{int(cy*scale_factor)},{int(cw*scale_factor)},{int(ch*scale_factor)})")
            
            win_png = capture_window_png(window_id=w.window_id)
            win_img = Image.open(__import__("io").BytesIO(win_png)).convert("RGB")
            
            # Apply scale factor to crop coordinates for Retina displays
            scaled_cx = int(cx * scale_factor)
            scaled_cy = int(cy * scale_factor)
            scaled_cw = int(cw * scale_factor)
            scaled_ch = int(ch * scale_factor)
            
            cropped = _crop_rect_from_image(win_img, x=scaled_cx, y=scaled_cy, w=scaled_cw, h=scaled_ch)
            if cropped.size != (OUT_W, OUT_H):
                cropped = cropped.resize((OUT_W, OUT_H), Image.Resampling.LANCZOS)
            from io import BytesIO

            buf = BytesIO()
            cropped.save(buf, format="PNG")
            pngs_by_tf[tf] = buf.getvalue()
    else:
        if layout is None:
            raise SystemExit(
                f"Layout file not found: {args.layout}\n\n"
                "Either create it first:\n"
                "  python mac/agent_charts_screen/calibrate_layout.py --out mac/agent_charts_screen/layout.json\n\n"
                "Or use per-window mode (no layout needed):\n"
                "  python mac/agent_charts_screen/capture_and_upload.py --per-tf-windows --layout mac/agent_charts_screen/layout.json --symbol BTCUSDT\n"
            )

        monitor = int(layout["monitor"])
        rects = layout["rects"]
        window_owner = args.window_owner or layout.get("window_owner")
        window_title = args.window_title or layout.get("window_title")

        if layout.get("timeframes_order") != TIMEFRAMES_ORDER:
            raise SystemExit("layout.json timeframes_order must be the fixed order")

        if window_owner or window_title:
            from window_capture import capture_window_png, find_window

            w = find_window(owner_substr=window_owner, title_substr=window_title)
            png = capture_window_png(window_id=w.window_id)
            img = Image.open(__import__("io").BytesIO(png)).convert("RGB")
        else:
            img = capture_monitor(monitor)

        pngs_by_tf = {}
        for item in rects:
            tf = item["tf"]
            pngs_by_tf[tf] = crop_resize_png(img, item, OUT_W, OUT_H)

    now = datetime.now(timezone.utc)

    liquidation_heatmap_png: bytes | None = None
    app_window = args.app_window or os.environ.get("APP_WINDOW")
    if args.include_liquidation_heatmap:
        liquidation_heatmap_window_owner = (
            args.liquidation_heatmap_window_owner
            or os.environ.get("LIQUIDATION_HEATMAP_WINDOW_OWNER")
            or os.environ.get("CG_WINDOW_OWNER")
            or "Safari"
        )
        liquidation_heatmap_window_title = (
            args.liquidation_heatmap_window_title
            or os.environ.get("LIQUIDATION_HEATMAP_WINDOW_TITLE")
            or os.environ.get("CG_WINDOW_TITLE")
            or "Liquidation Heatmap"
        )

        if args.debug_env:
            print(f"liquidation_heatmap mode: window_owner={liquidation_heatmap_window_owner!r}")
            print(f"liquidation_heatmap mode: window_title={liquidation_heatmap_window_title!r}")

        _refresh_safari_tab(
            title_substr=liquidation_heatmap_window_title,
            wait_seconds=args.liquidation_heatmap_refresh_wait_seconds,
            debug=args.debug_env,
        )

        from window_capture import capture_window_png, find_window, get_window_scale_factor

        w = find_window(
            owner_substr=liquidation_heatmap_window_owner,
            title_substr=liquidation_heatmap_window_title,
        )
        win_png = capture_window_png(window_id=w.window_id)
        win_img = Image.open(__import__("io").BytesIO(win_png)).convert("RGB")

        liquidation_heatmap_crop_cfg = (layout or {}).get("liquidation_heatmap") or {}

        def _env_liquidation_heatmap_int(name: str) -> int | None:
            v = os.environ.get(name)
            if v is None or not v.strip():
                return None
            return int(v)

        liquidation_heatmap_cx = (
            args.liquidation_heatmap_crop_x
            if args.liquidation_heatmap_crop_x is not None
            else liquidation_heatmap_crop_cfg.get("x")
        )
        liquidation_heatmap_cy = (
            args.liquidation_heatmap_crop_y
            if args.liquidation_heatmap_crop_y is not None
            else liquidation_heatmap_crop_cfg.get("y")
        )
        liquidation_heatmap_cw = (
            args.liquidation_heatmap_crop_w
            if args.liquidation_heatmap_crop_w is not None
            else liquidation_heatmap_crop_cfg.get("w")
        )
        liquidation_heatmap_ch = (
            args.liquidation_heatmap_crop_h
            if args.liquidation_heatmap_crop_h is not None
            else liquidation_heatmap_crop_cfg.get("h")
        )
        if liquidation_heatmap_cx is None:
            liquidation_heatmap_cx = _env_liquidation_heatmap_int("CG_CROP_X")
        if liquidation_heatmap_cy is None:
            liquidation_heatmap_cy = _env_liquidation_heatmap_int("CG_CROP_Y")
        if liquidation_heatmap_cw is None:
            liquidation_heatmap_cw = _env_liquidation_heatmap_int("CG_CROP_W")
        if liquidation_heatmap_ch is None:
            liquidation_heatmap_ch = _env_liquidation_heatmap_int("CG_CROP_H")

        if all(v is not None for v in [liquidation_heatmap_cx, liquidation_heatmap_cy, liquidation_heatmap_cw, liquidation_heatmap_ch]):
            liquidation_heatmap_scale = get_window_scale_factor(window_id=w.window_id)
            scaled = {
                "x": int(liquidation_heatmap_cx * liquidation_heatmap_scale),
                "y": int(liquidation_heatmap_cy * liquidation_heatmap_scale),
                "w": int(liquidation_heatmap_cw * liquidation_heatmap_scale),
                "h": int(liquidation_heatmap_ch * liquidation_heatmap_scale),
            }
            liquidation_heatmap_img = _crop_rect_from_image(
                win_img,
                x=scaled["x"],
                y=scaled["y"],
                w=scaled["w"],
                h=scaled["h"],
            )
        else:
            liquidation_heatmap_img = win_img

        if liquidation_heatmap_img.size != (OUT_W, LIQUIDATION_HEATMAP_OUT_H):
            liquidation_heatmap_img = liquidation_heatmap_img.resize(
                (OUT_W, LIQUIDATION_HEATMAP_OUT_H),
                Image.Resampling.LANCZOS,
            )

        from io import BytesIO

        liquidation_heatmap_buf = BytesIO()
        liquidation_heatmap_img.save(liquidation_heatmap_buf, format="PNG")
        liquidation_heatmap_png = liquidation_heatmap_buf.getvalue()

        if app_window:
            _focus_app_window(app_window_substr=app_window, debug=args.debug_env)

    timeout = httpx.Timeout(args.http_timeout_seconds, connect=20.0)
    with httpx.Client(timeout=timeout) as client:
        if args.case_id:
            r = client.post(f"{base_url}/v1/cases/{args.case_id}/upload-urls")
        else:
            r = client.post(f"{base_url}/v1/cases/create")
        if r.status_code >= 400:
            raise SystemExit(
                f"case bootstrap failed with HTTP {r.status_code}.\n"
                f"Response body:\n{r.text}"
            )
        create = r.json()
        case_id = create["case_id"]
        upload_urls = create["upload_urls"]
        extra_upload_urls = create.get("extra_upload_urls") or {}

        for tf in TIMEFRAMES_ORDER:
            url = upload_urls[tf]
            png = pngs_by_tf[tf]
            put = client.put(url, content=png, headers={"Content-Type": "image/png"})
            if put.status_code >= 400:
                raise SystemExit(
                    f"Upload failed for timeframe {tf} with HTTP {put.status_code}.\n"
                    f"Response body:\n{put.text}"
                )

        if liquidation_heatmap_png is not None:
            liquidation_heatmap_url = extra_upload_urls.get("liquidation_heatmap")
            if not liquidation_heatmap_url:
                raise SystemExit(
                    "Server did not return extra_upload_urls.liquidation_heatmap. "
                    "Restart server with updated code and try again."
                )
            liquidation_heatmap_put = client.put(
                liquidation_heatmap_url,
                content=liquidation_heatmap_png,
                headers={"Content-Type": "image/png"},
            )
            if liquidation_heatmap_put.status_code >= 400:
                raise SystemExit(
                    f"Upload failed for liquidation heatmap with HTTP {liquidation_heatmap_put.status_code}.\n"
                    f"Response body:\n{liquidation_heatmap_put.text}"
                )

        analyze_body = {
            "symbol": args.symbol,
            "timestamp_utc": now.isoformat(),
            "timeframes_order": TIMEFRAMES_ORDER,
        }
        if args.vision_provider:
            analyze_body["vision_provider"] = args.vision_provider
        if args.vision_model_pass1:
            analyze_body["vision_model_pass1"] = args.vision_model_pass1
        if args.vision_model_pass2:
            analyze_body["vision_model_pass2"] = args.vision_model_pass2
        if liquidation_heatmap_png is not None:
            analyze_body["include_liquidation_heatmap"] = True
            if args.liquidation_heatmap_time_horizon_hours is not None:
                analyze_body["liquidation_heatmap_time_horizon_hours"] = args.liquidation_heatmap_time_horizon_hours
        a = client.post(f"{base_url}/v1/cases/{case_id}/analyze", json=analyze_body)
        if a.status_code >= 400:
            raise SystemExit(
                f"/v1/cases/{case_id}/analyze failed with HTTP {a.status_code}.\n"
                f"Response body:\n{a.text}"
            )

        print(json.dumps(a.json(), indent=2))


if __name__ == "__main__":
    main()
