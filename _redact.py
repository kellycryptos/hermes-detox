"""Hermes Agent redaction integration.

Follows maintainer review on PR 150642.
Detox redacts sensitive text and terminal output using Hermes core's redact
helpers before storing or building reports.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def is_redact_available() -> bool:
    """Return True if Hermes core redaction helpers are importable."""
    try:
        from agent.redact import redact_sensitive_text, redact_terminal_output  # noqa: F401
        return True
    except Exception:
        return False


def redact_sensitive_text(text: str, *, force: bool = True) -> Optional[str]:
    """Redact sensitive patterns in tool output.

    Returns None if Hermes core redaction helpers are unavailable.
    """
    try:
        from agent.redact import redact_sensitive_text as core_redact_text
        return core_redact_text(text, force=force)
    except Exception as exc:
        logger.debug("redact_sensitive_text unavailable: %s", exc)
        return None


def redact_terminal_output(output: str, command: Optional[str] = None) -> Optional[str]:
    """Redact terminal output.

    Returns None if Hermes core redaction helpers are unavailable.
    """
    try:
        from agent.redact import redact_terminal_output as core_redact_terminal
        return core_redact_terminal(output, command)
    except Exception as exc:
        logger.debug("redact_terminal_output unavailable: %s", exc)
        return None
