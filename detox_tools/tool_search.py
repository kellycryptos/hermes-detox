"""Tool handler for detox_search."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from store import EvidenceStore

logger = logging.getLogger("hermes_detox.tool_search")

SCHEMA = {
    "name": "detox_search",
    "description": "Search across stored original tool outputs for specific phrases or errors.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Substring or phrase to find in the stored outputs.",
            },
            "evidence_id": {
                "type": "string",
                "description": "Scope search to a specific evidence ID. If omitted, searches current session.",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether the match should be case-sensitive. Defaults to false.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of matching lines to return. Defaults to 20.",
            },
        },
        "required": ["query"],
    },
}


def handle_detox_search(args: Dict[str, Any], session_id: Optional[str] = None, **kwargs: Any) -> str:
    """Handler for detox_search tool. Never raises; always returns JSON string."""
    try:
        if not isinstance(args, dict):
            return json.dumps({
                "success": False,
                "error": f"Invalid args: expected dict, got {type(args).__name__}",
            })

        query = args.get("query")
        if not query or not isinstance(query, str):
            return json.dumps({
                "success": False,
                "error": "Missing required argument 'query'",
            })

        evidence_id = args.get("evidence_id")
        case_sensitive = bool(args.get("case_sensitive", False))
        limit = int(args.get("limit", 20))

        effective_session_id = session_id or kwargs.get("session_id")
        store = EvidenceStore.get_instance()
        # When an explicit evidence_id is provided, search targets that specific record.
        # When evidence_id is omitted, search is strictly scoped to the active session
        # to prevent cross-session leakage.
        search_session_id = None if evidence_id else effective_session_id
        result = store.search_lines(
            query=query,
            evidence_id=evidence_id,
            session_id=search_session_id,
            case_sensitive=case_sensitive,
            limit=limit,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("Error executing detox_search: %s", exc)
        return json.dumps({
            "success": False,
            "error": f"Internal detox_search error: {str(exc)}",
        })
