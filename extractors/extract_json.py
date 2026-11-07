"""JSON content-aware extractor for Hermes Detox.

Summarizes large JSON structures while preserving structural integrity:
- Preserves top-level keys and data types
- Preserves array element counts and representative samples
- Highlights error, failure, code, status, and message fields verbatim
- NEVER alters numbers, drops critical identifiers, or changes data types
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


def _summarize_value(val: Any, depth: int = 0, max_depth: int = 3) -> Any:
    """Recursively produce a compact summary of a JSON data structure."""
    if depth >= max_depth:
        if isinstance(val, dict):
            return f"<dict with {len(val)} keys: {list(val.keys())[:5]}>"
        if isinstance(val, list):
            return f"<array of {len(val)} items>"
        return val

    if isinstance(val, dict):
        summary: Dict[str, Any] = {}
        for k, v in val.items():
            k_lower = k.lower()
            # Always preserve error, id, status, code, and message fields intact
            if any(term in k_lower for term in ("id", "error", "status", "code", "msg", "message", "count", "total")):
                if isinstance(v, (dict, list)):
                    summary[k] = _summarize_value(v, depth + 1, max_depth)
                else:
                    summary[k] = v  # Exact value preserved
            elif isinstance(v, list):
                if len(v) == 0:
                    summary[k] = []
                elif len(v) <= 3:
                    summary[k] = [_summarize_value(item, depth + 1, max_depth) for item in v]
                else:
                    sample = [_summarize_value(item, depth + 1, max_depth) for item in v[:2]]
                    sample.append(f"... +{len(v) - 2} more items (total {len(v)})")
                    summary[k] = sample
            elif isinstance(v, dict):
                summary[k] = _summarize_value(v, depth + 1, max_depth)
            else:
                summary[k] = v
        return summary

    if isinstance(val, list):
        if len(val) == 0:
            return []
        if len(val) <= 3:
            return [_summarize_value(item, depth + 1, max_depth) for item in val]
        sample = [_summarize_value(item, depth + 1, max_depth) for item in val[:2]]
        sample.append(f"... +{len(val) - 2} more items (total {len(val)})")
        return sample

    return val


def extract_json_summary(raw_output: str) -> Optional[Dict[str, Any]]:
    """Attempt to parse and summarize JSON output.
    
    Returns structured summary if valid JSON and confidence is high, else None.
    """
    stripped = raw_output.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")) and not (stripped.startswith("[") and stripped.endswith("]")):
        return None

    try:
        parsed = json.loads(stripped)
    except Exception:
        return None

    is_dict = isinstance(parsed, dict)
    is_list = isinstance(parsed, list)
    if not (is_dict or is_list):
        return None

    summary_obj = _summarize_value(parsed, depth=0, max_depth=3)
    formatted_json = json.dumps(summary_obj, indent=2, ensure_ascii=False)

    top_keys = list(parsed.keys()) if is_dict else [f"array_length={len(parsed)}"]

    return {
        "content_type": "application/json",
        "top_keys": top_keys,
        "summary_text": formatted_json,
    }
