from __future__ import annotations

import json
import re
from typing import Any


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_first_json_object(text: str) -> Any:
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError("No JSON object found in model output")
    return json.loads(m.group(0))
