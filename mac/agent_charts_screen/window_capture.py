from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WindowMatch:
    window_id: int
    owner_name: str
    window_name: str
    bounds: dict[str, int]


def _require_quartz():
    try:
        import Quartz  # type: ignore

        return Quartz
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Quartz window capture is unavailable. Install dependency with:\n\n"
            "  python -m pip install -r mac/agent_charts_screen/requirements.txt\n"
        ) from e


def list_windows() -> list[WindowMatch]:
    Quartz = _require_quartz()

    # Use kCGWindowListOptionAll to include windows from all virtual desktops/Spaces
    options = Quartz.kCGWindowListOptionAll
    window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []

    out: list[WindowMatch] = []
    for w in window_list:
        owner = str(w.get("kCGWindowOwnerName") or "")
        name = str(w.get("kCGWindowName") or "")
        wid = int(w.get("kCGWindowNumber") or 0)
        b = w.get("kCGWindowBounds") or {}
        # Normalize ObjC dict to plain python dict
        bounds = {
            "X": int(b.get("X") or 0),
            "Y": int(b.get("Y") or 0),
            "Width": int(b.get("Width") or 0),
            "Height": int(b.get("Height") or 0),
        }
        if wid <= 0:
            continue
        out.append(WindowMatch(window_id=wid, owner_name=owner, window_name=name, bounds=bounds))
    return out


def find_window(*, owner_substr: str | None = None, title_substr: str | None = None) -> WindowMatch:
    owner_substr_l = owner_substr.lower() if owner_substr else None
    title_substr_l = title_substr.lower() if title_substr else None

    matches: list[WindowMatch] = []
    windows = list_windows()
    for w in windows:
        if owner_substr_l and owner_substr_l not in w.owner_name.lower():
            continue
        if title_substr_l and title_substr_l not in w.window_name.lower():
            continue
        matches.append(w)

    if not matches:
        owner_candidates = [
            f"{w.owner_name} | {w.window_name} | id={w.window_id}"
            for w in windows
            if (not owner_substr_l or owner_substr_l in w.owner_name.lower())
        ][:30]
        raise RuntimeError(
            "No matching window found.\n"
            f"owner_substr={owner_substr!r}, title_substr={title_substr!r}\n\n"
            "Visible windows (filtered by owner if provided):\n"
            + "\n".join(["- " + s for s in owner_candidates])
            + "\n\nTry loosening --window-owner/--window-title, or run list_windows.py."
        )

    # Heuristic: pick the first match (CGWindowListCopyWindowInfo is ordered top-to-bottom)
    return matches[0]


def get_window_scale_factor(*, window_id: int) -> float:
    """
    Detect Retina scaling by comparing logical bounds vs captured image size.
    Returns 2.0 for Retina displays, 1.0 for non-Retina.
    """
    Quartz = _require_quartz()
    
    # Get logical bounds
    options = Quartz.kCGWindowListOptionIncludingWindow
    window_list = Quartz.CGWindowListCopyWindowInfo(options, window_id) or []
    if not window_list:
        return 1.0
    
    bounds = window_list[0].get("kCGWindowBounds") or {}
    logical_width = int(bounds.get("Width") or 0)
    
    # Get physical image size
    image = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        window_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming,
    )
    if image is None:
        return 1.0
    
    physical_width = Quartz.CGImageGetWidth(image)
    
    if logical_width > 0:
        scale = physical_width / logical_width
        return round(scale)  # Usually 1.0 or 2.0
    return 1.0


def capture_window_png(*, window_id: int) -> bytes:
    Quartz = _require_quartz()

    image = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        window_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming,
    )
    if image is None:
        raise RuntimeError("Failed to capture window image")

    # Convert CGImage -> PNG bytes
    import io

    from PIL import Image

    width = Quartz.CGImageGetWidth(image)
    height = Quartz.CGImageGetHeight(image)
    bytes_per_row = Quartz.CGImageGetBytesPerRow(image)

    data_provider = Quartz.CGImageGetDataProvider(image)
    data = Quartz.CGDataProviderCopyData(data_provider)

    # Quartz gives BGRA with row stride; respect bytes_per_row to avoid corruption.
    pil_rgba = Image.frombytes(
        "RGBA",
        (width, height),
        bytes(data),
        "raw",
        "BGRA",
        bytes_per_row,
        1,
    )
    pil = pil_rgba.convert("RGB")

    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()
