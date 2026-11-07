"""Stage 2 extractor tests for Hermes Detox.

Each test is grounded in the actual return shape of the extractor under test.
No mocking of extractor internals — inputs are real fixtures, assertions match
the documented contract of each function.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import os
import pathlib
import types
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap: insert project root so relative imports resolve correctly.
# ---------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Individual extractor tests
# ---------------------------------------------------------------------------

class TestJsonExtractor(unittest.TestCase):
    """extract_json_summary — parse large_data.json fixture."""

    def setUp(self):
        from extractors.extract_json import extract_json_summary
        self.extract = extract_json_summary
        self.raw = _load_fixture("large_data.json")

    def test_content_type(self):
        result = self.extract(self.raw)
        self.assertIsNotNone(result, "extract_json_summary should not return None for valid JSON")
        self.assertEqual(result["content_type"], "application/json")

    def test_status_key_preserved_verbatim(self):
        """'status' field must be preserved exactly (not retyped or omitted)."""
        import json as _json
        parsed = _json.loads(self.raw)
        expected_status = parsed["status"]          # "partial_failure"

        result = self.extract(self.raw)
        summary_obj = _json.loads(result["summary_text"])
        self.assertEqual(summary_obj.get("status"), expected_status)

    def test_error_count_key_present(self):
        """'error_count' is a critical identifier — must appear in summary."""
        import json as _json
        result = self.extract(self.raw)
        summary_obj = _json.loads(result["summary_text"])
        self.assertIn("error_count", summary_obj)
        # Value must be exact integer, not stringified
        self.assertIsInstance(summary_obj["error_count"], int)

    def test_records_array_summarized(self):
        """Large 'records' array must be summarised, not dropped."""
        import json as _json
        result = self.extract(self.raw)
        summary_obj = _json.loads(result["summary_text"])
        self.assertIn("records", summary_obj)
        records = summary_obj["records"]
        # Summarized: 2 real items + 1 "… +N more" string
        self.assertIsInstance(records, list)
        self.assertGreater(len(records), 0)
        # Last element is the summary string
        last = records[-1]
        self.assertIsInstance(last, str, "last element of summarised array should be '... +N more' string")
        self.assertIn("more", last)

    def test_top_keys_returned(self):
        result = self.extract(self.raw)
        self.assertIn("top_keys", result)
        self.assertIsInstance(result["top_keys"], list)
        self.assertGreater(len(result["top_keys"]), 0)

    def test_invalid_json_returns_none(self):
        result = self.extract("this is not JSON at all")
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        result = self.extract("")
        self.assertIsNone(result)


class TestTestExtractor(unittest.TestCase):
    """extract_test_summary — parse pytest_failures.txt fixture."""

    def setUp(self):
        from extractors.extract_tests import extract_test_summary
        self.extract = extract_test_summary
        self.raw = _load_fixture("pytest_failures.txt")

    def test_failed_count(self):
        result = self.extract(self.raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["failed"], 2)

    def test_passed_count(self):
        result = self.extract(self.raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["passed"], 22)

    def test_first_failure_name_in_summary(self):
        result = self.extract(self.raw)
        self.assertIn("test_order_creation_total", result["summary_text"])

    def test_second_failure_name_in_summary(self):
        result = self.extract(self.raw)
        self.assertIn("test_payment_charge_retry", result["summary_text"])

    def test_content_type_is_pytest(self):
        result = self.extract(self.raw)
        self.assertIsNotNone(result)
        self.assertIn("pytest", result["content_type"])

    def test_no_test_output_returns_none(self):
        result = self.extract("Random prose with no test framework markers")
        self.assertIsNone(result)


class TestBuildExtractor(unittest.TestCase):
    """extract_build_summary — parse build_errors.txt fixture."""

    def setUp(self):
        from extractors.extract_build import extract_build_summary
        self.extract = extract_build_summary
        self.raw = _load_fixture("build_errors.txt")

    def test_error_count_at_least_three(self):
        result = self.extract(self.raw)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["error_count"], 3)

    def test_auth_c_in_summary(self):
        result = self.extract(self.raw)
        self.assertIn("src/auth.c:45", result["summary_text"])

    def test_engine_cpp_in_summary(self):
        result = self.extract(self.raw)
        self.assertIn("src/engine.cpp:112", result["summary_text"])

    def test_undefined_reference_captured(self):
        """Linker 'undefined reference' must appear — it's a dependency failure."""
        result = self.extract(self.raw)
        self.assertIn("undefined reference", result["summary_text"].lower())

    def test_content_type(self):
        result = self.extract(self.raw)
        self.assertEqual(result["content_type"], "text/x-build-log")

    def test_clean_output_returns_none(self):
        clean = "[1/1] Building C object main.c.o\nBuild complete."
        result = self.extract(clean)
        self.assertIsNone(result)


class TestTerminalExtractor(unittest.TestCase):
    """extract_terminal_summary — parse terminal_failure.txt fixture."""

    def setUp(self):
        from extractors.extract_terminal import extract_terminal_summary
        self.extract = extract_terminal_summary
        self.raw = _load_fixture("terminal_failure.txt")

    def test_exit_code_is_one(self):
        result = self.extract(self.raw, status="error", returncode=1)
        self.assertIsNotNone(result)
        self.assertEqual(result["exit_code"], 1)

    def test_traceback_lines_captured(self):
        """The ConnectionRefusedError traceback must appear in summary_text."""
        result = self.extract(self.raw, status="error", returncode=1)
        self.assertIn("Traceback", result["summary_text"])

    def test_content_type(self):
        result = self.extract(self.raw, status="error", returncode=1)
        self.assertEqual(result["content_type"], "text/x-terminal")

    def test_exit_code_inferred_from_status_error(self):
        """When returncode is None but status='error', exit_code should default to 1."""
        result = self.extract(self.raw, status="error", returncode=None)
        self.assertIsNotNone(result)
        self.assertEqual(result["exit_code"], 1)

    def test_always_returns_dict(self):
        """Terminal extractor always returns a dict (never None) for any input."""
        result = self.extract("some output", status="success", returncode=0)
        self.assertIsNotNone(result)
        self.assertIn("exit_code", result)


class TestFileListingExtractor(unittest.TestCase):
    """extract_file_listing_summary — parse directory_tree.txt fixture."""

    def setUp(self):
        from extractors.extract_files import extract_file_listing_summary
        self.extract = extract_file_listing_summary
        self.raw = _load_fixture("directory_tree.txt")

    def test_package_json_notable(self):
        result = self.extract(self.raw)
        self.assertIsNotNone(result)
        notable_lower = [f.lower() for f in result["notable_files"]]
        self.assertTrue(any("package.json" in f for f in notable_lower))

    def test_env_notable(self):
        result = self.extract(self.raw)
        notable_lower = [f.lower() for f in result["notable_files"]]
        self.assertTrue(any(".env" in f for f in notable_lower))

    def test_dockerfile_notable(self):
        result = self.extract(self.raw)
        notable_lower = [f.lower() for f in result["notable_files"]]
        self.assertTrue(any("dockerfile" in f for f in notable_lower))

    def test_content_type(self):
        result = self.extract(self.raw)
        self.assertEqual(result["content_type"], "text/x-file-listing")

    def test_total_entries_positive(self):
        result = self.extract(self.raw)
        self.assertGreater(result["total_entries"], 0)

    def test_too_short_returns_none(self):
        """Fewer than 15 lines should return None (confidence too low)."""
        short = "./src/index.ts\n./README.md\n"
        result = self.extract(short)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Dispatcher (detect_and_extract_summary) tests
# ---------------------------------------------------------------------------

class TestDispatcher(unittest.TestCase):
    """detect_and_extract_summary routes tool outputs to the right extractor."""

    def setUp(self):
        from extractors import detect_and_extract_summary
        self.dispatch = detect_and_extract_summary

    def test_routes_json_payload(self):
        """A tool returning JSON should route to the JSON extractor."""
        json_output = _load_fixture("large_data.json")
        result = self.dispatch(tool_name="api_query", raw_output=json_output)
        self.assertIsNotNone(result)
        self.assertEqual(result["content_type"], "application/json")

    def test_routes_pytest_output(self):
        """A tool named 'run_pytest' with test output should route to the test extractor."""
        pytest_output = _load_fixture("pytest_failures.txt")
        result = self.dispatch(tool_name="run_pytest", raw_output=pytest_output)
        self.assertIsNotNone(result)
        self.assertIn("pytest", result["content_type"])

    def test_routes_file_listing_by_tool_name(self):
        """Tool named 'list_files' should try the file listing extractor."""
        listing_output = _load_fixture("directory_tree.txt")
        result = self.dispatch(tool_name="list_files", raw_output=listing_output)
        self.assertIsNotNone(result)
        self.assertEqual(result["content_type"], "text/x-file-listing")

    def test_routes_build_log_by_tool_name(self):
        """Tool named 'run_build' should try the build extractor."""
        build_output = _load_fixture("build_errors.txt")
        result = self.dispatch(tool_name="run_build", raw_output=build_output)
        self.assertIsNotNone(result)
        self.assertEqual(result["content_type"], "text/x-build-log")

    def test_fallback_returns_none_for_plain_prose(self):
        """Plain prose with no headings, errors, or test/build markers returns None."""
        prose = (
            "The quick brown fox jumps over the lazy dog. "
            "This is a plain paragraph with no technical markers whatsoever. "
            "It has no errors, warnings, or file paths at all."
        )
        result = self.dispatch(tool_name="generic_tool", raw_output=prose)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Report integration test
# ---------------------------------------------------------------------------

class TestReportWithExtractorSummary(unittest.TestCase):
    """build_compact_report uses extractor_summary when provided."""

    def setUp(self):
        from report import build_compact_report
        self.build_report = build_compact_report

    def test_extractor_summary_section_appears(self):
        """When extractor_summary is given, the '--- Extracted Summary ---' block appears."""
        output = self.build_report(
            tool_name="run_pytest",
            original_output="line1\nline2\nline3\nline4\nline5\nline6\n",
            evidence_id="evid-test-001",
            extractor_summary={
                "content_type": "text/x-pytest",
                "summary_text": "Framework: pytest\nStatus: FAILED\nTotals: 5 passed, 1 failed, 0 skipped",
            },
        )
        self.assertIn("Extracted Summary", output)
        self.assertIn("Framework: pytest", output)

    def test_extractor_content_type_in_header(self):
        """content_type from extractor should appear in the DETOX FIREWALL header."""
        output = self.build_report(
            tool_name="api_call",
            original_output="x" * 100,
            evidence_id="evid-test-002",
            extractor_summary={
                "content_type": "application/json",
                "summary_text": '{"status": "ok"}',
            },
        )
        self.assertIn("application/json", output)

    def test_no_extractor_summary_still_works(self):
        """build_compact_report without extractor_summary must still produce valid output."""
        output = self.build_report(
            tool_name="some_tool",
            original_output="a\nb\nc\nd\ne\nf\n",
            evidence_id="evid-test-003",
        )
        self.assertIn("DETOX FIREWALL", output)
        self.assertIn("evid-test-003", output)


class TestExtractorGroundTruthFidelity(unittest.TestCase):
    """Rigorous verification:
    1. Every line displayed with a line number (N | <text>) matches the exact line in original at index N.
    2. Every error line in original output either appears in the compact report or is retrievable by line number.
    Catches fabricated or shifted line numbers across all extractors.
    """

    def setUp(self):
        from store import EvidenceStore, set_storage_dir_override
        import tempfile
        self.temp_dir = tempfile.TemporaryDirectory()
        set_storage_dir_override(pathlib.Path(self.temp_dir.name))
        EvidenceStore.reset_instance()
        self.store = EvidenceStore.get_instance()

    def tearDown(self):
        from store import EvidenceStore, set_storage_dir_override
        EvidenceStore.reset_instance()
        set_storage_dir_override(None)
        self.temp_dir.cleanup()

    def _verify_fidelity(self, tool_name: str, raw_output: str, status: str = "success"):
        import re
        from report import build_compact_report, _ERROR_PATTERNS
        from extractors import detect_and_extract_summary

        orig_lines = raw_output.splitlines()
        ev_id = self.store.save("fid_sess", tool_name, raw_output, 0)

        extractor_summary = detect_and_extract_summary(
            tool_name=tool_name,
            raw_output=raw_output,
            status=status,
        )

        report = build_compact_report(
            tool_name=tool_name,
            original_output=raw_output,
            evidence_id=ev_id,
            status=status,
            extractor_summary=extractor_summary,
        )

        # 1. Assert no line printed with "N | text" is shifted or fabricated
        preview_pattern = re.compile(r"^\s*(\d+)(?:\s+\[(?:ERROR|WARN)\])?\s*\|\s*(.*)$", re.MULTILINE)
        matches = preview_pattern.findall(report)
        self.assertGreater(len(matches), 0, f"Report for {tool_name} must contain preview lines")

        for line_str, content in matches:
            line_no = int(line_str)
            self.assertGreaterEqual(line_no, 1, f"Line number {line_no} must be >= 1")
            self.assertLessEqual(line_no, len(orig_lines), f"Line {line_no} out of bounds (total {len(orig_lines)})")
            expected_content = orig_lines[line_no - 1]
            self.assertEqual(
                content.strip(),
                expected_content.strip(),
                f"Line number {line_no} has shifted content!\nGot:      {content}\nExpected: {expected_content}",
            )

        # 2. Assert every error line in original is in the report OR retrievable by exact line number
        for idx, line in enumerate(orig_lines, start=1):
            if _ERROR_PATTERNS.search(line):
                in_report = line.strip() in report
                retrieval = self.store.get_lines(ev_id, start_line=idx, end_line=idx, session_id="fid_sess")
                self.assertTrue(retrieval["success"], f"Line {idx} failed retrieval")
                self.assertEqual(retrieval["lines"][0].strip(), line.strip())
                self.assertTrue(
                    in_report or retrieval["success"],
                    f"Error on line {idx} was neither in report nor retrievable!",
                )

    def test_fidelity_pytest_extractor(self):
        raw = _load_fixture("pytest_failures.txt")
        self._verify_fidelity("run_pytest", raw, status="error")

    def test_fidelity_build_extractor(self):
        raw = _load_fixture("build_errors.txt")
        self._verify_fidelity("run_build", raw, status="error")

    def test_fidelity_terminal_extractor(self):
        raw = _load_fixture("terminal_failure.txt")
        self._verify_fidelity("terminal", raw, status="error")

    def test_fidelity_file_listing_extractor(self):
        raw = _load_fixture("directory_tree.txt")
        self._verify_fidelity("list_files", raw, status="success")

    def test_fidelity_json_extractor(self):
        raw = _load_fixture("large_data.json")
        self._verify_fidelity("api_fetch", raw, status="error")

    def test_fidelity_plain_text_extractor(self):
        # 100 lines of plain log with scattered errors
        lines = [f"Log trace item {i}: worker thread active" for i in range(1, 101)]
        lines[14] = "Log trace item 15: ERROR - connection pool exhausted"
        lines[72] = "Log trace item 73: WARNING - slow query detected: 4500ms"
        raw = "\n".join(lines)
        self._verify_fidelity("application_log", raw, status="success")


# ---------------------------------------------------------------------------
# Stage 1 regression guard
# ---------------------------------------------------------------------------

class TestStage1Regression(unittest.TestCase):
    """Re-runs the original 10 Stage 1 tests via subprocess to confirm no regression."""

    def test_stage1_tests_still_pass(self):
        import subprocess
        uv = r"C:\Users\HP\.local\bin\uv.exe"
        test_path = str(PROJECT_ROOT / "tests" / "test_core.py")
        result = subprocess.run(
            [uv, "run", "python", test_path, "-v"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"Stage 1 tests failed.\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}",
        )
        self.assertIn("OK", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
