"""Compiler and build tool content-aware extractor for Hermes Detox.

Parses build outputs from gcc/clang, rustc/cargo build, TypeScript (tsc), and bundlers (vite, webpack, esbuild):
- Compiler errors and warnings
- Source file paths and line coordinates
- Missing dependency and linking failures
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Patterns matching standard compiler/linter error diagnostics:
# Example: src/main.rs:14:5: error[E0308]: mismatched types
# Example: src/index.ts(42,15): error TS2339: Property 'x' does not exist
# Example: main.c:88:12: error: expected ';' before 'return'
_COMPILER_DIAGNOSTIC_RE = re.compile(
    r"(?P<file>[a-zA-Z0-9_\-\./\\]+):(?P<line>\d+)(?::(?P<col>\d+))?:\s*(?P<severity>error|fatal error|warning)(?:\[(?P<code>[A-Za-z0-9_]+)\])?:\s*(?P<msg>[^\n]+)",
    re.IGNORECASE,
)

_TS_DIAGNOSTIC_RE = re.compile(
    r"(?P<file>[a-zA-Z0-9_\-\./\\]+)[\(:](?P<line>\d+)(?:,\d+)?[\)]?:\s*(?P<severity>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>[^\n]+)",
    re.IGNORECASE,
)

_DEPENDENCY_ERROR_RE = re.compile(
    r"(module not found|cannot find module|undefined reference to|ld returned \d+ exit status|failed to resolve import)",
    re.IGNORECASE,
)


def extract_build_summary(raw_output: str) -> Optional[Dict[str, Any]]:
    """Detect and summarize build logs and compiler diagnostics."""
    lines = raw_output.splitlines()

    diagnostics: List[Tuple[int, str, str, str]] = []  # (orig_line_no, severity, file_loc, msg)
    dependency_issues: List[Tuple[int, str]] = []

    for idx, line in enumerate(lines, start=1):
        if len(line) > 300:
            target_line = line[:300]
        else:
            target_line = line

        # Quick substring pre-filter: compiler diagnostics always contain ':' or '('
        if ":" not in target_line and "(" not in target_line:
            if _DEPENDENCY_ERROR_RE.search(target_line):
                dependency_issues.append((idx, target_line.strip()))
            continue

        m = _COMPILER_DIAGNOSTIC_RE.search(target_line)
        if m:
            d = m.groupdict()
            file_loc = f"{d['file']}:{d['line']}"
            msg = f"{d.get('code') or ''} {d['msg']}".strip()
            diagnostics.append((idx, d["severity"].upper(), file_loc, msg))
            continue

        ts_m = _TS_DIAGNOSTIC_RE.search(target_line)
        if ts_m:
            d = ts_m.groupdict()
            file_loc = f"{d['file']}:{d['line']}"
            msg = f"{d['code']}: {d['msg']}"
            diagnostics.append((idx, d["severity"].upper(), file_loc, msg))
            continue

        if _DEPENDENCY_ERROR_RE.search(target_line):
            dependency_issues.append((idx, target_line.strip()))

    if not diagnostics and not dependency_issues:
        return None

    error_count = sum(1 for _, sev, _, _ in diagnostics if "ERROR" in sev) + len(dependency_issues)
    warn_count = sum(1 for _, sev, _, _ in diagnostics if "WARN" in sev)

    summary_lines = [
        "Category: Compiler / Build Log",
        f"Status: {'FAILED' if error_count > 0 else 'COMPLETED WITH WARNINGS'}",
        f"Issues Found: {error_count} error(s), {warn_count} warning(s)",
    ]

    if dependency_issues:
        summary_lines.append("")
        summary_lines.append("Dependency / Linking Failures:")
        for line_no, dep in dependency_issues[:5]:
            summary_lines.append(f"{line_no:4d} | {dep}")

    if diagnostics:
        summary_lines.append("")
        summary_lines.append("Compiler Diagnostics:")
        for line_no, sev, loc, msg in diagnostics[:20]:
            summary_lines.append(f"{line_no:4d} [{sev}] {loc} — {msg}")

    return {
        "content_type": "text/x-build-log",
        "error_count": error_count,
        "warning_count": warn_count,
        "summary_text": "\n".join(summary_lines),
    }
