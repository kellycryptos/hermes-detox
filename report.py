"""Compact report generator for Hermes Detox.

Transforms large or noisy tool outputs into a clear, structured summary
that preserves critical error messages and provides exact retrieval cues.
Supports content-aware extractor summaries for JSON, tests, builds, listings, and terminal.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_ERROR_PATTERNS = re.compile(
    r"(error|fatal|exception|traceback|failed|failure|panic|cannot find|not found|"
    r"syntaxerror|typeerror|valueerror|runtimeerror|assert|permission denied|"
    r"undefined|referenceerror|corrupted|timed out|timeout)",
    re.IGNORECASE,
)

_WARNING_PATTERNS = re.compile(
    r"(warning|warn|deprecated|deprecation|caution)",
    re.IGNORECASE,
)


def extract_diagnostic_lines(lines: List[str], max_matches: int = 40) -> List[Tuple[int, str, str]]:
    """Scan lines for errors and warnings, returning (line_number_1_based, severity, text)."""
    matches: List[Tuple[int, str, str]] = []
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if _ERROR_PATTERNS.search(stripped):
            matches.append((idx, "ERROR", line))
        elif _WARNING_PATTERNS.search(stripped):
            matches.append((idx, "WARN", line))
        if len(matches) >= max_matches:
            break
    return matches


def build_compact_report(
    tool_name: str,
    original_output: str,
    evidence_id: str,
    status: str = "success",
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    head_lines_count: int = 5,
    tail_lines_count: int = 5,
    extractor_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a deterministic, informative compact report for LLM context."""
    lines = original_output.splitlines()
    total_lines = len(lines)
    orig_chars = len(original_output)

    # 1. Error Status Verbatim Block (amendment requirement)
    error_verbatim_block = ""
    is_error = (status == "error") or bool(error_type) or bool(error_message)
    if is_error:
        error_parts = []
        if error_type:
            error_parts.append(f"Error Type: {error_type}")
        if error_message:
            error_parts.append(f"Error Message: {error_message}")
        if not error_parts:
            err_matches = extract_diagnostic_lines(lines, max_matches=10)
            if err_matches:
                error_parts.append("Error Output: " + "; ".join(m[2].strip() for m in err_matches[:3]))
            else:
                error_parts.append("Status: Error detected in execution")
        error_verbatim_block = "\n".join(f"> [!CRITICAL] {part}" for part in error_parts) + "\n\n"

    report_lines: List[str] = []
    category_suffix = f" ({extractor_summary['content_type']})" if (extractor_summary and "content_type" in extractor_summary) else ""
    report_lines.append(f"=== [DETOX FIREWALL: {tool_name}]{category_suffix} ===")
    report_lines.append(
        f"Original output ({orig_chars:,} chars, {total_lines:,} lines) saved to evidence: `{evidence_id}`"
    )
    report_lines.append("")

    if error_verbatim_block:
        report_lines.append(error_verbatim_block.strip())
        report_lines.append("")

    # 2. Content-Aware Extractor Summary (if available)
    if extractor_summary and extractor_summary.get("summary_text"):
        report_lines.append("--- Extracted Summary ---")
        report_lines.append(extractor_summary["summary_text"].strip())
        report_lines.append("")

    # 3. Head preview
    head = lines[:head_lines_count]
    tail = lines[-tail_lines_count:] if total_lines > head_lines_count else []

    report_lines.append(f"--- Head (Lines 1-{len(head)}) ---")
    for i, l in enumerate(head, start=1):
        report_lines.append(f"{i:4d} | {l}")

    # 4. Diagnostic findings (errors, warnings, failures with line numbers)
    diagnostics = extract_diagnostic_lines(lines)
    if diagnostics:
        unseen = [
            (line_no, sev, l) for line_no, sev, l in diagnostics
            if line_no > len(head) and (not tail or line_no <= total_lines - len(tail))
        ]
        if unseen:
            report_lines.append("")
            report_lines.append(f"--- Diagnostic Findings ({len(unseen)} lines) ---")
            for line_no, sev, l in unseen:
                report_lines.append(f"{line_no:4d} [{sev}] | {l}")

    # 5. Tail preview
    if tail and (total_lines > head_lines_count):
        tail_start = total_lines - len(tail) + 1
        report_lines.append("")
        report_lines.append(f"--- Tail (Lines {tail_start}-{total_lines}) ---")
        for i, l in enumerate(tail, start=tail_start):
            report_lines.append(f"{i:4d} | {l}")

    # 6. Actionable Retrieval Instructions
    report_lines.append("")
    report_lines.append("--- Retrieval ---")
    report_lines.append(
        f"To inspect exact lines, call `detox_inspect(evidence_id=\"{evidence_id}\", start_line=<N>, end_line=<M>)`."
    )
    report_lines.append(
        f"To search lines, call `detox_search(evidence_id=\"{evidence_id}\", query=\"<phrase>\")`."
    )
    report_lines.append(f"=== [END DETOX REPORT `{evidence_id}`] ===")

    return "\n".join(report_lines)
