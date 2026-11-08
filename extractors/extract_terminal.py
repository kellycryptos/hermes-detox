"""Terminal process content-aware extractor for Hermes Detox.

Parses command-line output streams:
- Exit codes and execution status
- Stack traces and traceback chains
- Failed commands and paths
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_TRACEBACK_START_RE = re.compile(r"Traceback \(most recent call last\):|panic:|FATAL ERROR:", re.IGNORECASE)
_STACK_FRAME_RE = re.compile(r'^\s*File "([^"]+)", line (\d+)', re.IGNORECASE)
_EXIT_STATUS_RE = re.compile(r"(exited with code|command failed with exit code|returned non-zero exit status)\s*(\d+)", re.IGNORECASE)


def extract_terminal_summary(
    raw_output: str,
    status: str = "success",
    returncode: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Detect and summarize terminal command output."""
    lines = raw_output.splitlines()
    total_lines = len(lines)

    exit_code = returncode
    traceback_lines: List[Tuple[int, str]] = []
    error_lines: List[Tuple[int, str]] = []

    in_traceback = False
    for idx, line in enumerate(lines, start=1):
        if len(line) > 300:
            target_line = line[:300]
        else:
            target_line = line

        if _TRACEBACK_START_RE.search(target_line):
            in_traceback = True

        if in_traceback:
            traceback_lines.append((idx, target_line.strip()))
            # Stop traceback block after error description line
            if not target_line.startswith(" ") and len(traceback_lines) > 2 and not target_line.startswith("Traceback"):
                in_traceback = False
        elif any(term in target_line.lower() for term in ("error:", "error ", "fatal:", "fatal ", "failed:", "exception:")):
            error_lines.append((idx, target_line.strip()))

        if exit_code is None:
            m = _EXIT_STATUS_RE.search(target_line)
            if m:
                exit_code = int(m.group(2))

    if exit_code is None and status == "error":
        exit_code = 1

    summary_lines = [
        "Category: Terminal Command Output",
        f"Status: {'FAILED' if (exit_code and exit_code != 0) or status == 'error' else 'SUCCESS'}",
    ]
    if exit_code is not None:
        summary_lines.append(f"Exit Code: {exit_code}")

    if traceback_lines:
        summary_lines.append("")
        summary_lines.append("Stack Trace:")
        for line_no, text in traceback_lines[:15]:
            summary_lines.append(f"{line_no:4d} | {text}")

    if error_lines and not traceback_lines:
        summary_lines.append("")
        summary_lines.append("Error Highlights:")
        for line_no, text in error_lines[:10]:
            summary_lines.append(f"{line_no:4d} | {text}")

    return {
        "content_type": "text/x-terminal",
        "exit_code": exit_code,
        "summary_text": "\n".join(summary_lines),
    }
