from __future__ import annotations

import json
import Quartz

def list_all_windows():
    """List ALL windows including minimized and hidden ones."""
    # kCGWindowListOptionAll includes minimized and hidden windows
    options = Quartz.kCGWindowListOptionAll
    window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
    
    tradingview_windows = []
    for w in window_list:
        owner = str(w.get("kCGWindowOwnerName") or "")
        if "trading" in owner.lower():
            name = str(w.get("kCGWindowName") or "")
            wid = int(w.get("kCGWindowNumber") or 0)
            b = w.get("kCGWindowBounds") or {}
            bounds = {
                "X": int(b.get("X") or 0),
                "Y": int(b.get("Y") or 0),
                "Width": int(b.get("Width") or 0),
                "Height": int(b.get("Height") or 0),
            }
            layer = w.get("kCGWindowLayer", "unknown")
            on_screen = w.get("kCGWindowIsOnscreen", False)
            
            tradingview_windows.append({
                "window_id": wid,
                "owner_name": owner,
                "window_name": name,
                "bounds": bounds,
                "layer": layer,
                "on_screen": on_screen,
            })
    
    return tradingview_windows

if __name__ == "__main__":
    windows = list_all_windows()
    if windows:
        print(f"Found {len(windows)} TradingView windows:")
        print(json.dumps(windows, indent=2))
    else:
        print("No TradingView windows found!")
        print("\nChecking if TradingView process is running...")
        import subprocess
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        if "TradingView" in result.stdout:
            print("✓ TradingView process is running")
            print("\nPossible reasons windows aren't showing:")
            print("1. Windows are minimized")
            print("2. Windows are on a different Space/Desktop")
            print("3. TradingView app is running but no chart windows are open")
        else:
            print("✗ TradingView process is NOT running")
