"""Hermes Detox — Tool Output Firewall Plugin for Hermes Agent.

Compresses oversized or noisy tool outputs into compact, informative reports,
stores the full originals securely in local SQLite storage, and enables the model
to retrieve exact lines on demand.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shlex
import sys
from typing import Any, Callable, Dict, Optional

# Ensure package root is importable without shadowing Hermes packages
_PKG_ROOT = Path(__file__).resolve().parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.append(str(_PKG_ROOT))

from detox_tools.tool_inspect import SCHEMA as INSPECT_SCHEMA, handle_detox_inspect
from detox_tools.tool_search import SCHEMA as SEARCH_SCHEMA, handle_detox_search
from detox_tools.tool_status import SCHEMA as STATUS_SCHEMA, handle_detox_status
from extractors import detect_and_extract_summary
from report import build_compact_report
from store import EvidenceStore

logger = logging.getLogger("hermes_detox")

# Default configuration parameters
DEFAULT_CONFIG = {
    "enabled": True,
    "min_size": 2000,
    "head_lines": 5,
    "tail_lines": 5,
    "excluded_tools": [],
}

_ACTIVE_CONFIG: Dict[str, Any] = dict(DEFAULT_CONFIG)


def get_active_config() -> Dict[str, Any]:
    """Return active configuration dictionary."""
    return _ACTIVE_CONFIG


def _load_plugin_config(ctx: Any) -> None:
    """Load configuration from Hermes context safely without network/heavy IO."""
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = dict(DEFAULT_CONFIG)
    try:
        if hasattr(ctx, "get_config") and callable(ctx.get_config):
            cfg = ctx.get_config()
            if isinstance(cfg, dict):
                _ACTIVE_CONFIG.update(cfg)
    except Exception as exc:
        logger.debug("Could not read ctx config, using defaults: %s", exc)


def on_transform_tool_result(
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    turn_id: str = "",
    api_request_id: str = "",
    duration_ms: int = 0,
    status: str = "success",
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    **kwargs: Any,
) -> Optional[str]:
    """Hook: transform oversized tool outputs into compact reports.
    
    Returns replacement string if compressed, or None to keep original output untouched.
    FAIL-OPEN: Any unexpected exception returns None.
    """
    try:
        cfg = _ACTIVE_CONFIG
        if not cfg.get("enabled", True):
            return None

        # Do not intercept Detox's own retrieval tools to prevent recursion loops
        if tool_name in ("detox_inspect", "detox_search", "detox_status"):
            return None

        # Check configured tool exclusions
        excluded = cfg.get("excluded_tools", [])
        if tool_name in excluded:
            return None

        # Ensure result is present and stringifiable
        if result is None:
            return None

        raw_output = result if isinstance(result, str) else str(result)
        raw_len = len(raw_output)

        min_threshold = int(cfg.get("min_size", 2000))

        # Small outputs stay completely unchanged
        if raw_len <= min_threshold:
            return None

        # Run content-aware extractor first
        extractor_res = detect_and_extract_summary(
            tool_name=tool_name,
            raw_output=raw_output,
            status=status or "success",
            error_type=error_type,
            error_message=error_message,
            **kwargs,
        )

        content_type = extractor_res.get("content_type", "text/plain") if extractor_res else "text/plain"

        store = EvidenceStore.get_instance()
        head_count = int(cfg.get("head_lines", 5))
        tail_count = int(cfg.get("tail_lines", 5))

        # Generate evidence ID and save original securely
        ev_id = store.save(
            session_id=session_id or "default",
            tool_name=tool_name,
            original_output=raw_output,
            transformed_size=0,
            content_type=content_type,
            status=status or "success",
        )

        compact_report = build_compact_report(
            tool_name=tool_name,
            original_output=raw_output,
            evidence_id=ev_id,
            status=status or "success",
            error_type=error_type,
            error_message=error_message,
            head_lines_count=head_count,
            tail_lines_count=tail_count,
            extractor_summary=extractor_res,
        )

        # Check compression ratio: only replace if report achieves significant reduction (at most ~half original size)
        max_ratio = float(cfg.get("max_ratio", 0.55))
        if len(compact_report) > raw_len * max_ratio:
            logger.debug(
                "Detox compact report (%d chars) did not achieve reduction threshold vs original (%d chars); keeping original",
                len(compact_report),
                raw_len,
            )
            return None

        # Update transformed size in store
        try:
            conn = store._get_conn()
            with conn:
                conn.execute(
                    "UPDATE evidence SET transformed_size = ? WHERE id = ?",
                    (len(compact_report), ev_id),
                )
        except Exception:
            pass

        return compact_report

    except Exception as exc:
        # FAIL OPEN: Log problem and return None to preserve original output untouched
        logger.error("Detox transform_tool_result failed open: %s", exc)
        return None


def on_transform_terminal_output(
    command: str = "",
    output: str = "",
    returncode: int = 0,
    task_id: str = "",
    env_type: str = "",
    **kwargs: Any,
) -> Optional[str]:
    """Hook: intercept terminal outputs before Hermes's 50k inline truncation drops the middle."""
    try:
        cfg = _ACTIVE_CONFIG
        if not cfg.get("enabled", True):
            return None

        if not output or len(output) <= int(cfg.get("min_size", 2000)):
            return None

        status = "success" if returncode == 0 else "error"
        extractor_res = detect_and_extract_summary(
            tool_name="terminal",
            raw_output=output,
            status=status,
            returncode=returncode,
            command=command,
            **kwargs,
        )

        content_type = extractor_res.get("content_type", "text/x-terminal") if extractor_res else "text/x-terminal"
        store = EvidenceStore.get_instance()
        session_id = kwargs.get("session_id", "default")

        # Pre-save un-truncated terminal evidence
        ev_id = store.save(
            session_id=session_id,
            tool_name="terminal",
            original_output=output,
            transformed_size=0,
            content_type=content_type,
            status=status,
        )

        report = build_compact_report(
            tool_name=f"terminal (`{command[:60]}`)" if command else "terminal",
            original_output=output,
            evidence_id=ev_id,
            status=status,
            head_lines_count=int(cfg.get("head_lines", 5)),
            tail_lines_count=int(cfg.get("tail_lines", 5)),
            extractor_summary=extractor_res,
        )

        # Check compression ratio: only replace if report achieves significant reduction (at most ~half original size)
        max_ratio = float(cfg.get("max_ratio", 0.55))
        if len(report) > len(output) * max_ratio:
            logger.debug(
                "Terminal report (%d chars) did not achieve reduction threshold vs original (%d chars); keeping original",
                len(report),
                len(output),
            )
            return None

        try:
            conn = store._get_conn()
            with conn:
                conn.execute(
                    "UPDATE evidence SET transformed_size = ? WHERE id = ?",
                    (len(report), ev_id),
                )
        except Exception:
            pass

        return report
    except Exception as exc:
        logger.error("Detox transform_terminal_output failed open: %s", exc)
        return None


def on_post_compaction(old_session_id: str = "", new_session_id: str = "", **kwargs: Any) -> None:
    """Relink stored evidence records when a session is compacted or migrated."""
    try:
        if old_session_id and new_session_id:
            store = EvidenceStore.get_instance()
            store.relink_session(old_session_id, new_session_id)
    except Exception as exc:
        logger.debug("on_post_compaction error: %s", exc)


def on_session_delete(session_id: str = "", **kwargs: Any) -> None:
    """Purge stored evidence records when a session is deleted."""
    try:
        if session_id:
            store = EvidenceStore.get_instance()
            store.purge_session(session_id)
    except Exception as exc:
        logger.debug("on_session_delete error: %s", exc)


def on_session_reset(session_id: str = "", **kwargs: Any) -> None:
    """Observer hook: purge stored evidence records when session is reset."""
    try:
        if session_id:
            store = EvidenceStore.get_instance()
            store.purge_session(session_id)
    except Exception as exc:
        logger.debug("on_session_reset error: %s", exc)


def handle_detox_slash_command(args: str) -> str:
    """Handle /detox slash command."""
    raw_args = args.strip() if args else ""
    if not raw_args or raw_args == "help":
        return (
            "Hermes Detox — Tool Output Firewall\n\n"
            "Commands:\n"
            "  /detox status                                - Show firewall savings metrics\n"
            "  /detox inspect <id> [start_line] [end_line]  - Inspect original lines\n"
            "  /detox search <phrase> [evidence_id]         - Search original outputs\n"
        )

    parts = shlex.split(raw_args)
    subcmd = parts[0].lower()

    if subcmd == "status":
        res = handle_detox_status({})
        data = json.loads(res)
        return (
            f"Detox Firewall Status:\n"
            f"  Outputs intercepted: {data.get('outputs_intercepted', 0):,}\n"
            f"  Characters in:       {data.get('characters_in', 0):,}\n"
            f"  Characters out:      {data.get('characters_out', 0):,}\n"
            f"  Characters saved:    {data.get('characters_saved', 0):,} ({data.get('saved_percentage', 0.0)}% reduction)"
        )

    if subcmd == "inspect":
        if len(parts) < 2:
            return "Usage: /detox inspect <evidence_id> [start_line] [end_line]"
        ev_id = parts[1]
        start_line = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
        end_line = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        res = handle_detox_inspect({"evidence_id": ev_id, "start_line": start_line, "end_line": end_line})
        data = json.loads(res)
        if not data.get("success"):
            return f"Error: {data.get('error')}"
        lines_out = []
        for line_no, text in zip(range(data["start_line"], data["end_line"] + 1), data.get("lines", [])):
            lines_out.append(f"{line_no:4d} | {text}")
        return "\n".join(lines_out)

    if subcmd == "search":
        if len(parts) < 2:
            return "Usage: /detox search <phrase> [evidence_id]"
        query = parts[1]
        ev_id = parts[2] if len(parts) > 2 else None
        res = handle_detox_search({"query": query, "evidence_id": ev_id})
        data = json.loads(res)
        if not data.get("success"):
            return f"Error: {data.get('error')}"
        matches = data.get("results", [])
        if not matches:
            return f"No lines matched '{query}'."
        lines_out = [f"Found {len(matches)} match(es) for '{query}':"]
        for m in matches:
            lines_out.append(f"[{m['evidence_id']}:{m['line_number']}] {m['line']}")
        return "\n".join(lines_out)

    return f"Unknown /detox sub-command: '{subcmd}'. Type `/detox help` for available options."


def register(ctx: Any) -> None:
    """Hermes plugin registration entrypoint."""
    _load_plugin_config(ctx)

    if hasattr(ctx, "register_hook") and callable(ctx.register_hook):
        ctx.register_hook("transform_tool_result", on_transform_tool_result)
        ctx.register_hook("transform_terminal_output", on_transform_terminal_output)

    if hasattr(ctx, "register_tool") and callable(ctx.register_tool):
        ctx.register_tool(
            name="detox_inspect",
            toolset="detox",
            schema=INSPECT_SCHEMA,
            handler=handle_detox_inspect,
        )
        ctx.register_tool(
            name="detox_search",
            toolset="detox",
            schema=SEARCH_SCHEMA,
            handler=handle_detox_search,
        )
        ctx.register_tool(
            name="detox_status",
            toolset="detox",
            schema=STATUS_SCHEMA,
            handler=handle_detox_status,
        )

    if hasattr(ctx, "register_command") and callable(ctx.register_command):
        ctx.register_command(
            name="detox",
            handler=handle_detox_slash_command,
            description="Inspect, search, and monitor Detox tool output firewall",
        )
