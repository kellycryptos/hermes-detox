"""Retention and disk cleanup policy enforcement for Hermes Detox.

Provides age-based expiration and size-cap pruning for stored tool outputs.
Cleanup runs throttled at session lifecycle events (session start/reset) or
via manual `/detox purge` commands — never in the hot path of tool result transformation.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional

from config import DetoxConfig, get_config
from store import EvidenceStore, resolve_data_dir

logger = logging.getLogger("hermes_detox.retention")

# In-memory timestamp of last successful retention check
_LAST_PRUNE_TIMESTAMP: float = 0.0


def _get_timestamp_marker_path() -> Path:
    """Return path to persistent retention last-run timestamp file."""
    return resolve_data_dir() / ".retention_marker"


def get_last_run_timestamp() -> float:
    """Return Unix timestamp of the last retention prune run."""
    global _LAST_PRUNE_TIMESTAMP
    if _LAST_PRUNE_TIMESTAMP > 0:
        return _LAST_PRUNE_TIMESTAMP

    marker = _get_timestamp_marker_path()
    try:
        if marker.exists():
            val = float(marker.read_text(encoding="utf-8").strip())
            _LAST_PRUNE_TIMESTAMP = val
            return val
    except Exception:
        pass
    return 0.0


def _record_run_timestamp(ts: float) -> None:
    """Record current timestamp in memory and marker file."""
    global _LAST_PRUNE_TIMESTAMP
    _LAST_PRUNE_TIMESTAMP = ts
    try:
        marker = _get_timestamp_marker_path()
        marker.write_text(str(ts), encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed writing retention timestamp marker: %s", exc)


def run_retention_prune(
    store: Optional[EvidenceStore] = None,
    config: Optional[DetoxConfig] = None,
) -> Dict[str, Any]:
    """Execute retention policy immediately (unthrottled).
    
    1. Purges evidence older than config.retention_days.
    2. Purges oldest evidence if database file exceeds config.max_store_size_mb.
    """
    st = store or EvidenceStore.get_instance()
    cfg = config or get_config()

    expired_count = 0
    size_cap_count = 0

    try:
        # 1. Age-based expiration
        if cfg.retention_days > 0:
            expired_count = st.purge_older_than(cfg.retention_days)

        # 2. Maximum store size enforcement
        if cfg.max_store_size_mb > 0:
            max_bytes = cfg.max_store_size_mb * 1024 * 1024
            size_cap_count = st.enforce_size_cap(max_bytes)

        _record_run_timestamp(time.time())

        current_size = st.get_db_size()
        remaining_records = st.count_records()

        logger.info(
            "Detox retention prune complete: %d expired purged, %d size-cap purged, %d records remaining (%d bytes)",
            expired_count,
            size_cap_count,
            remaining_records,
            current_size,
        )

        return {
            "success": True,
            "expired_purged": expired_count,
            "size_cap_purged": size_cap_count,
            "total_purged": expired_count + size_cap_count,
            "current_db_bytes": current_size,
            "records_remaining": remaining_records,
        }
    except Exception as exc:
        logger.error("Detox retention prune failed: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "expired_purged": expired_count,
            "size_cap_purged": size_cap_count,
            "total_purged": expired_count + size_cap_count,
            "current_db_bytes": st.get_db_size(),
            "records_remaining": st.count_records(),
        }


def maybe_run_retention_prune(
    store: Optional[EvidenceStore] = None,
    config: Optional[DetoxConfig] = None,
    min_interval_secs: int = 21600,  # 6 hours default throttle
) -> Optional[Dict[str, Any]]:
    """Run retention cleanup if more than min_interval_secs has elapsed since last run.
    
    Safe to call at session start or session reset — throttled to prevent redundant disk I/O.
    """
    now = time.time()
    last = get_last_run_timestamp()

    if (now - last) < min_interval_secs:
        logger.debug("Retention prune throttled (last run %.1f hours ago)", (now - last) / 3600.0)
        return None

    return run_retention_prune(store=store, config=config)
