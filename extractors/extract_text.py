"""Plain text content-aware extractor for Hermes Detox.

Parses structural markdown headings and error phrases without semantic extrapolation:
- Markdown and ASCII section headings
- Diagnostic keywords with line coordinates
- Makes NO semantic or synthetic understanding claims
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_HEADING_RE = re.compile(r"^(?:#{1,6}\s+|[A-Z0-9_\-\s]{3,30}:|\={3,}|\-{3,})")
_ERROR_KEYWORD_RE = re.compile(r"\b(error|failed|failure|fatal|warning|exception)\b", re.IGNORECASE)


def extract_plain_text_summary(raw_output: str) -> Optional[Dict[str, Any]]:
    """Extract structural headings and error phrases from plain text."""
    lines = raw_output.splitlines()
    if len(lines) < 10:
        return None

    headings: List[Tuple[int, str]] = []
    error_contexts: List[Tuple[int, str]] = []

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADING_RE.match(stripped) and len(stripped) < 100:
            headings.append((idx, stripped))
        elif _ERROR_KEYWORD_RE.search(stripped):
            error_contexts.append((idx, stripped))

    if not headings and not error_contexts:
        return None

    summary_lines = [
        "Category: Plain Text / Document Structure",
        f"Detected Headings: {len(headings)}",
    ]

    if headings:
        summary_lines.append("")
        summary_lines.append("Section Headings:")
        for line_no, h in headings[:10]:
            summary_lines.append(f"{line_no:4d} | {h}")

    if error_contexts:
        summary_lines.append("")
        summary_lines.append(f"Diagnostic Mentions ({len(error_contexts)} found):")
        for line_no, err in error_contexts[:8]:
            summary_lines.append(f"{line_no:4d} | {err}")

    return {
        "content_type": "text/plain",
        "headings_count": len(headings),
        "summary_text": "\n".join(summary_lines),
    }
