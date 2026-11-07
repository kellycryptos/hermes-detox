"""Content-aware extractors package for Hermes Detox.

Routes tool outputs to specialized extractors (JSON, test suites, build logs,
file listings, terminal streams, and structural text) with deterministic,
safe fallback to generic reporting.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from extractors.extract_build import extract_build_summary
from extractors.extract_files import extract_file_listing_summary
from extractors.extract_json import extract_json_summary
from extractors.extract_terminal import extract_terminal_summary
from extractors.extract_tests import extract_test_summary
from extractors.extract_text import extract_plain_text_summary

logger = logging.getLogger("hermes_detox.extractors")


def detect_and_extract_summary(
    tool_name: str,
    raw_output: str,
    status: str = "success",
    returncode: Optional[int] = None,
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """Inspect tool output and route to the most confident specialized extractor.
    
    Returns extractor result dict if high confidence, or None for safe generic fallback.
    """
    tool_lower = (tool_name or "").lower()

    # 1. JSON tool results or JSON payloads
    if raw_output.lstrip().startswith(("{", "[")):
        try:
            res = extract_json_summary(raw_output)
            if res is not None:
                return res
        except Exception as exc:
            logger.debug("JSON extraction skipped: %s", exc)

    # 2. Test runner tools (pytest, unittest, jest, cargo test)
    if any(k in tool_lower for k in ("test", "pytest", "jest", "unit")) or "test result:" in raw_output or "=== FAILURES ===" in raw_output:
        try:
            res = extract_test_summary(raw_output)
            if res is not None:
                return res
        except Exception as exc:
            logger.debug("Test extraction skipped: %s", exc)

    # 3. Compiler / build tools (gcc, clang, cargo build, tsc, vite, make)
    if any(k in tool_lower for k in ("build", "compile", "gcc", "clang", "tsc", "cargo", "make")):
        try:
            res = extract_build_summary(raw_output)
            if res is not None:
                return res
        except Exception as exc:
            logger.debug("Build extraction skipped: %s", exc)

    # 4. File listings (find, ls, tree, dir)
    if any(k in tool_lower for k in ("find", "ls", "tree", "dir", "list_files", "glob")):
        try:
            res = extract_file_listing_summary(raw_output)
            if res is not None:
                return res
        except Exception as exc:
            logger.debug("File listing extraction skipped: %s", exc)

    # 5. Terminal / shell / log outputs
    if any(k in tool_lower for k in ("terminal", "bash", "shell", "exec", "cmd", "run", "log")):
        try:
            res = extract_terminal_summary(raw_output, status=status, returncode=returncode)
            if res is not None:
                return res
        except Exception as exc:
            logger.debug("Terminal extraction skipped: %s", exc)

    # 6. Secondary scan: try build or test detection on generic terminal outputs
    try:
        test_res = extract_test_summary(raw_output)
        if test_res is not None:
            return test_res

        build_res = extract_build_summary(raw_output)
        if build_res is not None:
            return build_res

        file_res = extract_file_listing_summary(raw_output)
        if file_res is not None:
            return file_res

        text_res = extract_plain_text_summary(raw_output)
        if text_res is not None:
            return text_res
    except Exception as exc:
        logger.debug("Secondary scan skipped: %s", exc)

    # Safe fallback: return None so generic report handles it cleanly
    return None
