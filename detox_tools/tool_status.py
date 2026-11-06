"""Tool handler for detox_status."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from store import EvidenceStore

logger = logging.getLogger("hermes_detox.tool_status")

SCHEMA = {
    "name": "detox_status",
    "description": "Report Detox firewall metrics: outputs intercepted, characters in, characters out, and token/character savings.",
    "parameters": {
        "type": "object",
        "properties": {
            "session_only": {
                "type": "boolean",
                "description": "If true, reports metrics for current session only. If false, reports global metrics.",
            },
        },
        "required": [],
    },
}


def handle_detox_status(args: Dict[str, Any] | None = None, session_id: Optional[str] = None, **kwargs: Any) -> str:
    """Handler for detox_status tool. Never raises; always returns JSON string."""
    try:
        args = args or {}
        session_only = bool(args.get("session_only", False))
        effective_session_id = (session_id or kwargs.get("session_id")) if session_only else None

        store = EvidenceStore.get_instance()
        metrics = store.status(session_id=effective_session_id)
        return json.dumps(metrics, ensure_ascii=False)
    except Exception as exc:
        logger.exception("Error executing detox_status: %s", exc)
        return json.dumps({
            "success": False,
            "error": f"Internal detox_status error: {str(exc)}",
        })
