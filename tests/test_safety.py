"""Stage 3 Safety, Concurrency, Retention, and Security Tests for Hermes Detox."""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import DetoxConfig, get_config, set_config
from detox_tools.tool_inspect import handle_detox_inspect
from detox_tools.tool_status import handle_detox_status
from retention import maybe_run_retention_prune, run_retention_prune
from store import EvidenceStore, set_storage_dir_override
import __init__ as detox_mod

on_transform_tool_result = detox_mod.on_transform_tool_result
on_session_reset = detox_mod.on_session_reset
handle_detox_slash_command = detox_mod.handle_detox_slash_command


class TestDetoxSafetyAndRetention(unittest.TestCase):
    """Test suite covering concurrency, retention pruning, and security guardrails."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="detox_safety_test_"))
        set_storage_dir_override(self.test_dir)
        EvidenceStore.reset_instance()
        set_config(DetoxConfig())

    def tearDown(self):
        EvidenceStore.reset_instance()
        set_storage_dir_override(None)
        set_config(DetoxConfig())
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_concurrent_writes_wal_mode(self):
        """10 concurrent threads inserting into SQLite WAL mode simultaneously.
        Verifies zero deadlocks, zero 'database is locked' errors, and 100% record integrity."""
        store = EvidenceStore.get_instance()
        num_threads = 10
        records_per_thread = 5

        def _worker(thread_idx: int) -> list[str]:
            thread_ids = []
            for item_idx in range(records_per_thread):
                body = f"Thread {thread_idx} log entry {item_idx}\n" + ("Payload data line\n" * 200)
                ev_id = store.save(
                    session_id=f"sess_thread_{thread_idx}",
                    tool_name="worker_tool",
                    original_output=body,
                    transformed_size=200,
                    content_type="text/plain",
                )
                thread_ids.append(ev_id)
            return thread_ids

        all_ids = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(_worker, i) for i in range(num_threads)]
            for fut in concurrent.futures.as_completed(futures):
                all_ids.extend(fut.result())

        self.assertEqual(len(all_ids), num_threads * records_per_thread)
        self.assertEqual(store.count_records(), num_threads * records_per_thread)

        # Confirm all records are cleanly readable
        for ev_id in all_ids:
            rec = store.get(ev_id)
            self.assertIsNotNone(rec, f"Record {ev_id} must exist in store")
            self.assertIn("Payload data line", rec["original_output"])

    def test_age_based_retention_prune(self):
        """Records older than retention_days are purged, while newer records are preserved."""
        store = EvidenceStore.get_instance()
        conn = store._get_conn()

        now = datetime.datetime.now(datetime.timezone.utc)
        ts_45d = (now - datetime.timedelta(days=45)).isoformat()
        ts_35d = (now - datetime.timedelta(days=35)).isoformat()
        ts_10d = (now - datetime.timedelta(days=10)).isoformat()
        ts_now = now.isoformat()

        with conn:
            conn.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ev_old_45", "s1", "t", ts_45d, "old 45 data", 11, 0, "text/plain", "success"),
            )
            conn.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ev_old_35", "s1", "t", ts_35d, "old 35 data", 11, 0, "text/plain", "success"),
            )
            conn.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ev_keep_10", "s1", "t", ts_10d, "keep 10 data", 12, 0, "text/plain", "success"),
            )
            conn.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ev_keep_now", "s1", "t", ts_now, "keep now data", 13, 0, "text/plain", "success"),
            )

        self.assertEqual(store.count_records(), 4)

        # Run age prune with 30 days retention
        purged = store.purge_older_than(30)
        self.assertEqual(purged, 2)
        self.assertEqual(store.count_records(), 2)

        self.assertIsNone(store.get("ev_old_45"))
        self.assertIsNone(store.get("ev_old_35"))
        self.assertIsNotNone(store.get("ev_keep_10"))
        self.assertIsNotNone(store.get("ev_keep_now"))

    def test_size_cap_retention_prune(self):
        """When database exceeds size cap, oldest records are pruned until within limit."""
        store = EvidenceStore.get_instance()
        now = datetime.datetime.now(datetime.timezone.utc)

        # Insert 10 records with sequential timestamps
        for i in range(10):
            ts = (now - datetime.timedelta(minutes=10 - i)).isoformat()
            payload = f"Payload {i}\n" + ("x" * 20000)
            conn = store._get_conn()
            with conn:
                conn.execute(
                    "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"ev_seq_{i}", "s1", "t", ts, payload, len(payload), 0, "text/plain", "success"),
                )

        initial_count = store.count_records()
        self.assertEqual(initial_count, 10)
        initial_size = store.get_db_size()
        self.assertGreater(initial_size, 50000)

        # Enforce size cap smaller than initial size
        purged = store.enforce_size_cap(initial_size // 2)
        self.assertGreater(purged, 0)
        remaining = store.count_records()
        self.assertLess(remaining, 10)
        # Oldest records should have been deleted first
        self.assertIsNone(store.get("ev_seq_0"))

    def test_retention_throttling(self):
        """Retention prune is throttled: running it twice in quick succession skips the second."""
        cfg = DetoxConfig(retention_days=30, max_store_size_mb=100)
        set_config(cfg)
        store = EvidenceStore.get_instance()

        res1 = maybe_run_retention_prune(store=store, config=cfg, min_interval_secs=3600)
        self.assertIsNotNone(res1)
        self.assertTrue(res1["success"])

        # Second call immediately after should be throttled (returns None)
        res2 = maybe_run_retention_prune(store=store, config=cfg, min_interval_secs=3600)
        self.assertIsNone(res2, "Subsequent prune within throttle window must return None")

    def test_redaction_behavior_with_secrets(self):
        """Verify secret handling across the store and outbound redaction pipeline.
        1. Raw secret is preserved in local SQLite database for exact fidelity.
        2. detox_inspect retrieves the raw line from SQLite verbatim.
        3. Hermes outbound redaction (agent.redact.redact_sensitive_text) masks secrets when enabled."""
        secret_token = "sk-ant-api03-abcdef1234567890abcdef1234567890"
        lines = [
            "Configuration initialized.",
            f"AUTH_TOKEN={secret_token}",
            "Connection established successfully.",
        ] + [f"Log stream record {i:04d}: Telemetry event packet payload data" for i in range(300)]
        raw_output = "\n".join(lines)

        report = on_transform_tool_result(
            tool_name="init_service",
            result=raw_output,
            session_id="sec_sess",
        )
        self.assertIsNotNone(report)

        store = EvidenceStore.get_instance()
        # Verify the raw unredacted secret is safely in SQLite
        conn = store._get_conn()
        row = conn.execute("SELECT original_output FROM evidence WHERE session_id = 'sec_sess'").fetchone()
        self.assertIn(secret_token, row[0], "Detox local store preserves exact original output")

        # Verify detox_inspect retrieves the line verbatim from SQLite
        import re
        ev_id = re.search(r"evidence: `(ev_[a-f0-9]+)`", report).group(1)
        inspect_raw = handle_detox_inspect({"evidence_id": ev_id, "start_line": 2, "end_line": 2}, session_id="sec_sess")
        inspect_data = json.loads(inspect_raw)
        self.assertEqual(inspect_data["lines"][0], f"AUTH_TOKEN={secret_token}")

        # Now test Hermes's outbound redaction layer
        try:
            from agent.redact import redact_sensitive_text
            masked = redact_sensitive_text(inspect_data["content"])
            self.assertNotIn(secret_token, masked, "Hermes outbound redactor must mask API key before LLM receives it")
        except ImportError:
            pass  # Standalone environment without Hermes agent package

    def test_excluded_tools_configuration(self):
        """Tools in excluded_tools configuration must never be intercepted, even if large."""
        cfg = DetoxConfig(min_size=6000, excluded_tools=["secret_dump_tool", "my_custom_tool"])
        set_config(cfg)

        large_payload = "Data row\n" * 800  # ~7,200 chars

        # Excluded tool -> returns None
        res_excluded = on_transform_tool_result(
            tool_name="secret_dump_tool",
            result=large_payload,
            session_id="excl_sess",
        )
        self.assertIsNone(res_excluded, "Excluded tool must return None")

        # Non-excluded tool -> intercepted
        res_normal = on_transform_tool_result(
            tool_name="normal_tool",
            result=large_payload,
            session_id="excl_sess",
        )
        self.assertIsNotNone(res_normal, "Non-excluded tool must be transformed")

    def test_fail_open_on_corrupt_database(self):
        """If SQLite database file is corrupted or unwriteable, fail open without crashing."""
        db_path = EvidenceStore.get_instance().db_path
        EvidenceStore.reset_instance()

        # Overwrite DB with corrupted binary data
        with open(db_path, "wb") as f:
            f.write(b"CORRUPTED_GARBAGE_BYTES_NOT_A_SQLITE_DATABASE" * 100)

        large_output = "System log line\n" * 600
        res = on_transform_tool_result(
            tool_name="critical_task",
            result=large_output,
            session_id="corrupt_sess",
        )
        self.assertIsNone(res, "Detox must fail open (return None) when database is corrupted")

    def test_slash_command_purge_and_status(self):
        """Test /detox purge and /detox status slash commands."""
        store = EvidenceStore.get_instance()
        large_output = "Diagnostic report\n" + ("log entry\n" * 400)
        on_transform_tool_result(tool_name="test_tool", result=large_output, session_id="cmd_sess")

        status_msg = handle_detox_slash_command("status")
        self.assertIn("Outputs intercepted:", status_msg)
        self.assertIn("Database size:", status_msg)
        self.assertIn("Stored records:", status_msg)

        purge_msg = handle_detox_slash_command("purge")
        self.assertIn("Detox Retention Purge Completed:", purge_msg)
        self.assertIn("Records remaining:", purge_msg)


if __name__ == "__main__":
    unittest.main()
