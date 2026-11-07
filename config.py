"""Configuration management for Hermes Detox.

Loads and normalizes plugin configuration from Hermes context or defaults.
Provides safe type coercion and sane operational limits.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hermes_detox.config")


DEFAULT_EXCLUDED_TOOLS = [
    "browser_vision",
    "browser_snapshot",
    "image_generate",
    "video_generate",
    "video_analyze",
    "vision_analyze",
    "text_to_speech",
    "patch",
    "write_file",
]


@dataclass
class DetoxConfig:
    """Strongly typed Detox firewall configuration."""

    enabled: bool = True
    min_size: int = 6000
    max_report_chars: int = 3000
    max_ratio: float = 0.55
    head_lines: int = 5
    tail_lines: int = 5
    excluded_tools: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDED_TOOLS))
    retention_days: int = 30
    max_store_size_mb: int = 100
    debug: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DetoxConfig":
        """Instantiate DetoxConfig from a raw dictionary with robust type coercion."""
        if not data or not isinstance(data, dict):
            return cls()

        def _to_bool(val: Any, default: bool) -> bool:
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.strip().lower() in ("true", "1", "yes", "on")
            if isinstance(val, (int, float)):
                return bool(val)
            return default

        def _to_int(val: Any, default: int, min_val: Optional[int] = None) -> int:
            try:
                res = int(val)
                if min_val is not None and res < min_val:
                    return min_val
                return res
            except (ValueError, TypeError):
                return default

        def _to_float(val: Any, default: float, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float:
            try:
                res = float(val)
                if min_val is not None and res < min_val:
                    return min_val
                if max_val is not None and res > max_val:
                    return max_val
                return res
            except (ValueError, TypeError):
                return default

        def _to_list_of_str(val: Any) -> Optional[List[str]]:
            if val is None:
                return None
            if isinstance(val, list):
                return [str(item).strip() for item in val if item is not None and str(item).strip()]
            if isinstance(val, str):
                return [item.strip() for item in val.split(",") if item.strip()]
            return None

        excluded = _to_list_of_str(data.get("excluded_tools"))
        if excluded is None:
            excluded = list(DEFAULT_EXCLUDED_TOOLS)

        return cls(
            enabled=_to_bool(data.get("enabled"), True),
            min_size=_to_int(data.get("min_size"), 6000, min_val=100),
            max_report_chars=_to_int(data.get("max_report_chars"), 3000, min_val=500),
            max_ratio=_to_float(data.get("max_ratio"), 0.55, min_val=0.1, max_val=1.0),
            head_lines=_to_int(data.get("head_lines"), 5, min_val=1),
            tail_lines=_to_int(data.get("tail_lines"), 5, min_val=1),
            excluded_tools=excluded,
            retention_days=_to_int(data.get("retention_days"), 30, min_val=1),
            max_store_size_mb=_to_int(data.get("max_store_size_mb"), 100, min_val=5),
            debug=_to_bool(data.get("debug"), False),
        )


_ACTIVE_CONFIG: DetoxConfig = DetoxConfig()


def get_config() -> DetoxConfig:
    """Return the active configuration object."""
    return _ACTIVE_CONFIG


def set_config(config: DetoxConfig) -> None:
    """Set active configuration."""
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = config
    if config.debug:
        logger.setLevel(logging.DEBUG)


def load_config(ctx: Any = None) -> DetoxConfig:
    """Load configuration from Hermes plugin context or defaults."""
    cfg_dict: Dict[str, Any] = {}
    if ctx is not None:
        try:
            if hasattr(ctx, "get_config") and callable(ctx.get_config):
                raw = ctx.get_config()
                if isinstance(raw, dict):
                    cfg_dict = raw
        except Exception as exc:
            logger.debug("Failed reading config from ctx, using defaults: %s", exc)

    config = DetoxConfig.from_dict(cfg_dict)
    set_config(config)
    return config
