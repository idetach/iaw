from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


def capture_monitor(monitor_index: int) -> Image.Image:
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        return img


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor", type=int, default=1, help="mss monitor index (1 is primary)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--window-owner", type=str, default=None, help="Substring match for window owner (e.g. TradingView)")
    parser.add_argument("--window-title", type=str, default=None, help="Substring match for window title")
    parser.add_argument(
        "--rect",
        action="append",
        default=[],
        help="Rect in form tf:x,y,w,h. Repeat 6 times for 4h,1h,30m,15m,5m,1m.",
    )
    parser.add_argument(
        "--screenshot-out",
        type=Path,
        default=Path("mac/agent_charts_screen/calibration_screenshot.png"),
        help="Where to write a captured full screenshot (used for manual calibration).",
    )
    parser.add_argument(
        "--screenshot-only",
        action="store_true",
        help="Only save the screenshot and exit (no rectangle UI/prompts).",
    )
    args = parser.parse_args()

    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

    try:
        if args.window_owner or args.window_title:
            from window_capture import capture_window_png, find_window

            w = find_window(owner_substr=args.window_owner, title_substr=args.window_title)
            png = capture_window_png(window_id=w.window_id)
            img = Image.open(__import__("io").BytesIO(png)).convert("RGB")
        else:
            img = capture_monitor(args.monitor)
    except Exception as e:
        raise SystemExit(f"Failed to capture screenshot: {e}")

    def parse_rect_spec(spec: str) -> dict[str, Any]:
        # tf:x,y,w,h
        try:
            tf, rest = spec.split(":", 1)
            parts = rest.split(",")
            if len(parts) != 4:
                raise ValueError
            x, y, w, h = [int(p.strip()) for p in parts]
            return {"tf": tf.strip(), "x": x, "y": y, "w": w, "h": h}
        except Exception as e:
            raise SystemExit(f"Invalid --rect '{spec}'. Expected tf:x,y,w,h") from e

    # Lazy import tkinter (not always present depending on Python distribution)
    try:
        import tkinter as tk
        from PIL import ImageTk
        has_tk = True
    except Exception:
        has_tk = False

    if not has_tk:
        args.screenshot_out.parent.mkdir(parents=True, exist_ok=True)
        img.save(args.screenshot_out)
        print("tkinter/_tkinter is not available in this Python build.")
        print(f"Saved a full screenshot to: {args.screenshot_out}")
        if args.screenshot_only:
            return
        print("Open it in Preview and determine rectangles for the chart area for each timeframe.")
        print("You can rerun with 6 --rect flags, e.g.:")
        print("  --rect 4h:10,20,300,200 --rect 1h:... (etc)")
        print("Or paste them interactively now.")

        rects_by_tf: dict[str, dict[str, Any]] = {}
        for spec in args.rect:
            r = parse_rect_spec(spec)
            rects_by_tf[r["tf"]] = r

        for tf in TIMEFRAMES_ORDER:
            if tf in rects_by_tf:
                continue
            raw = input(f"Enter rect for {tf} as x,y,w,h: ").strip()
            parts = raw.split(",")
            if len(parts) != 4:
                raise SystemExit("Expected x,y,w,h")
            x, y, w, h = [int(p.strip()) for p in parts]
            rects_by_tf[tf] = {"tf": tf, "x": x, "y": y, "w": w, "h": h}

        out = {
            "monitor": args.monitor,
            "window_owner": args.window_owner,
            "window_title": args.window_title,
            "timeframes_order": TIMEFRAMES_ORDER,
            "rects": [rects_by_tf[tf] for tf in TIMEFRAMES_ORDER],
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"Saved layout to {args.out}")
        return

    root = tk.Tk()
    root.title("calibrate_layout: draw 6 rectangles (drag) in order 4h,1h,30m,15m,5m,1m")

    tk_img = ImageTk.PhotoImage(img)
    canvas = tk.Canvas(root, width=img.width, height=img.height)
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=tk_img)

    rects: list[Rect] = []
    current = {"x0": 0, "y0": 0, "rid": None}

    label = tk.Label(root, text=f"Draw rectangle for {TIMEFRAMES_ORDER[len(rects)]}")
    label.pack()

    def on_down(event):
        if len(rects) >= 6:
            return
        current["x0"], current["y0"] = event.x, event.y
        if current["rid"] is not None:
            canvas.delete(current["rid"])
            current["rid"] = None

    def on_drag(event):
        if len(rects) >= 6:
            return
        x0, y0 = current["x0"], current["y0"]
        x1, y1 = event.x, event.y
        if current["rid"] is not None:
            canvas.coords(current["rid"], x0, y0, x1, y1)
        else:
            current["rid"] = canvas.create_rectangle(x0, y0, x1, y1, outline="red", width=2)

    def on_up(event):
        if len(rects) >= 6:
            return
        x0, y0 = current["x0"], current["y0"]
        x1, y1 = event.x, event.y
        x = int(min(x0, x1))
        y = int(min(y0, y1))
        w = int(abs(x1 - x0))
        h = int(abs(y1 - y0))
        if w < 10 or h < 10:
            return
        rects.append(Rect(x=x, y=y, w=w, h=h))
        canvas.create_rectangle(x, y, x + w, y + h, outline="lime", width=2)
        if len(rects) < 6:
            label.configure(text=f"Draw rectangle for {TIMEFRAMES_ORDER[len(rects)]}")
        else:
            label.configure(text="Done. Close window to save layout.")

    canvas.bind("<ButtonPress-1>", on_down)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_up)

    root.mainloop()

    if len(rects) != 6:
        raise SystemExit(f"Expected 6 rectangles, got {len(rects)}")

    out = {
        "monitor": args.monitor,
        "window_owner": args.window_owner,
        "window_title": args.window_title,
        "timeframes_order": TIMEFRAMES_ORDER,
        "rects": [{"tf": tf, "x": r.x, "y": r.y, "w": r.w, "h": r.h} for tf, r in zip(TIMEFRAMES_ORDER, rects)],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Saved layout to {args.out}")


if __name__ == "__main__":
    main()
