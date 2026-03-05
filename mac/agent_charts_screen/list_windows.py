from __future__ import annotations

import json

from window_capture import list_windows


def main() -> None:
    wins = list_windows()
    print(
        json.dumps(
            [
                {
                    "window_id": w.window_id,
                    "owner_name": w.owner_name,
                    "window_name": w.window_name,
                    "bounds": dict(w.bounds),
                }
                for w in wins
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
