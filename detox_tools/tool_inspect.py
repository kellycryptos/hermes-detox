"""Tool handler for detox_inspect."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from store import EvidenceStore

logger = logging.getLogger("hermes_detox.tool_inspect")

SCHEMA = {
    "name": "detox_inspect",
    "description": "Retrieve exact lines from an original tool output stored by Detox.",
    "parameters": {
        "type": "object",
        "properties": {
            "evidence_id": {
                "type": "string",
                "description": "The evidence ID returned in the Detox compact report (e.g. 'ev_abc123').",
            },
            "start_line": {
                "type": "integer",
                "description": "1-based starting line number to retrieve. Defaults to 1.",
            },
            "end_line": {
                "type": "integer",
                "description": "1-based ending line number (inclusive). If omitted, retrieves to end of file.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return before truncating. Optional safety ceiling.",
            },
        },
        "required": ["evidence_id"],
    },
}


def handle_detox_inspect(args: Dict[str, Any], session_id: Optional[str] = None, **kwargs: Any) -> str:
    """Handler for detox_inspect tool. Never raises; always returns JSON string."""
    try:
        if not isinstance(args, dict):
            return json.dumps({
                "success": False,
                "error": f"Invalid args: expected dict, got {type(args).__name__}",
            })

        evidence_id = args.get("evidence_id")
        if not evidence_id or not isinstance(evidence_id, str):
            return json.dumps({
                "success": False,
                "error": "Missing required argument 'evidence_id'",
            })

        start_line = int(args.get("start_line", 1))
        end_line_raw = args.get("end_line")
        end_line = int(end_line_raw) if end_line_raw is not None else None
        max_chars_raw = args.get("max_chars")
        max_chars = int(max_chars_raw) if max_chars_raw is not None else None

        # Explicit, unguessable evidence ID acts as direct capability authorization,
        # allowing exact line inspection across sessions in the same profile (e.g. after
        # context compaction rotates the session ID).
        store = EvidenceStore.get_instance()
        result = store.get_lines(
            evidence_id=evidence_id,
            start_line=start_line,
            end_line=end_line,
            max_chars=max_chars,
            session_id=None,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("Error executing detox_inspect: %s", exc)
        return json.dumps({
            "success": False,
            "error": f"Internal detox_inspect error: {str(exc)}",
        })
