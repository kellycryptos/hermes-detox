"""Test runner content-aware extractor for Hermes Detox.

Parses outputs from pytest, python unittest, jest/vitest, cargo test, and go test:
- Totals: passed, failed, skipped/ignored
- Specific failed test identifiers
- Assertion messages and key failure traces
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_PYTEST_SUMMARY_RE = re.compile(
    r"(=+\s*(?:(?P<failed>\d+)\s+failed)?(?:[,\s]+(?P<passed>\d+)\s+passed)?(?:[,\s]+(?P<skipped>\d+)\s+skipped)?.*in\s+[\d\.]+s\s*=+|(?P<failures_only>\d+)\s+failed)",
    re.IGNORECASE,
)

_UNITTEST_SUMMARY_RE = re.compile(
    r"FAILED\s*\((?:failures=(?P<failures>\d+))?(?:[,\s]*errors=(?P<errors>\d+))?(?:[,\s]*skipped=(?P<skipped>\d+))?\)",
    re.IGNORECASE,
)

_CARGO_TEST_RE = re.compile(
    r"test result:\s*(?P<status>FAILED|ok)\.\s*(?P<passed>\d+)\s+passed;\s*(?P<failed>\d+)\s+failed;\s*(?P<ignored>\d+)\s+ignored",
    re.IGNORECASE,
)

_GO_TEST_RE = re.compile(r"--- FAIL:\s*(?P<test>[^\s]+)\s*\((?P<time>[\d\.]+)s\)", re.IGNORECASE)

_TEST_FAILURE_LINE_RE = re.compile(
    r"(FAILED\s+[^\s]+|FAIL:\s+[^\s]+|FAIL\s+[^\s]+|✕\s+[^\n]+|AssertionError:?|assert\s+.+==)",
    re.IGNORECASE,
)


def extract_test_summary(raw_output: str) -> Optional[Dict[str, Any]]:
    """Detect and summarize test suite execution results."""
    lines = raw_output.splitlines()
    total_lines = len(lines)

    passed: Optional[int] = None
    failed: Optional[int] = None
    skipped: Optional[int] = None
    framework = "test_runner"

    # 1. Check for pytest summary
    for line in lines[-15:]:
        m = _PYTEST_SUMMARY_RE.search(line)
        if m:
            framework = "pytest"
            d = m.groupdict()
            if d.get("failed"):
                failed = int(d["failed"])
            elif d.get("failures_only"):
                failed = int(d["failures_only"])
            if d.get("passed"):
                passed = int(d["passed"])
            if d.get("skipped"):
                skipped = int(d["skipped"])
            break

    # 2. Check for unittest summary
    if failed is None:
        for line in lines[-10:]:
            m = _UNITTEST_SUMMARY_RE.search(line)
            if m:
                framework = "unittest"
                d = m.groupdict()
                fails = int(d.get("failures") or 0)
                errs = int(d.get("errors") or 0)
                failed = fails + errs
                skipped = int(d.get("skipped") or 0)
                break

    # 3. Check for cargo test summary
    if failed is None:
        for line in lines[-10:]:
            m = _CARGO_TEST_RE.search(line)
            if m:
                framework = "cargo_test"
                d = m.groupdict()
                passed = int(d["passed"])
                failed = int(d["failed"])
                skipped = int(d["ignored"])
                break

    # 4. Check for go test failures
    go_fails = []
    for line in lines:
        m = _GO_TEST_RE.search(line)
        if m:
            go_fails.append(m.group("test"))
    if go_fails:
        framework = "go_test"
        failed = len(go_fails)

    # If no recognized test metrics were found, return None to trigger fallback
    if failed is None and passed is None:
        return None

    # Collect failure names and assertion lines with line numbers
    failure_entries: List[Tuple[int, str]] = []
    in_failure_section = False

    for idx, line in enumerate(lines, start=1):
        if "=== FAILURES ===" in line or "FAILURES" in line:
            in_failure_section = True
        if _TEST_FAILURE_LINE_RE.search(line):
            failure_entries.append((idx, line.strip()))
        elif in_failure_section and any(term in line for term in ("E   ", ">   ", "AssertionError", "Expected:", "Received:")):
            failure_entries.append((idx, line.strip()))
        if len(failure_entries) >= 25:
            break

    summary_lines = [
        f"Framework: {framework}",
        f"Status: {'FAILED' if (failed and failed > 0) else 'PASSED'}",
        f"Totals: {passed if passed is not None else 0} passed, {failed if failed is not None else 0} failed, {skipped if skipped is not None else 0} skipped",
    ]

    if failure_entries:
        summary_lines.append("")
        summary_lines.append(f"Notable Failure Details ({len(failure_entries)} lines extracted):")
        for line_no, text in failure_entries:
            summary_lines.append(f"{line_no:4d} | {text}")

    return {
        "content_type": f"text/x-{framework}",
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "summary_text": "\n".join(summary_lines),
    }
