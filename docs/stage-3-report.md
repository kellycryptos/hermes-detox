# Stage 3 Verification Report: Safety, Config, Retention & Security

**Status:** COMPLETE & PASSING  
**Commit:** `7e53e45` — `feat: Stage 3 config management, throttled retention, and safety tests`  
**Test Suite:** 70/70 tests passing (17 core, 45 extractors, 8 safety)

---

## 1. Summary of Deliverables

Stage 3 hardens Hermes Detox with typed configuration management, non-blocking throttled retention pruning, multi-threaded SQLite WAL concurrency guarantees, and comprehensive security/redaction disclosures.

1. **`config.py`**:
   - Strongly-typed `DetoxConfig` dataclass with safe type coercion and validation guards.
   - Defaults: `enabled: true`, `min_size: 6000`, `max_report_chars: 3000`, `max_ratio: 0.55`, `head_lines: 5`, `tail_lines: 5`, `excluded_tools: []`, `retention_days: 30`, `max_store_size_mb: 100`, `debug: false`.
   - `load_config(ctx)` safely queries `ctx.get_config()` without external dependencies.
2. **`retention.py`**:
   - `purge_older_than(days)`: Purges records older than `retention_days` and runs passive WAL checkpoints.
   - `enforce_size_cap(max_bytes)`: Sequentially evicts oldest evidence records when database file size exceeds `max_store_size_mb` and runs `PRAGMA wal_checkpoint(TRUNCATE)`.
   - `maybe_run_retention_prune()`: Throttled runner (default 6-hour interval via in-memory and marker file timestamp). Fired on `on_session_reset`, **never** executed inside the `transform_tool_result` transformation hot-path.
3. **`store.py` Extensions**:
   - Added `count_records(session_id)`, `get_db_size()` (calculates combined byte size of main DB, `-wal`, and `-shm` files), `purge_older_than()`, and `enforce_size_cap()`.
4. **Slash Command Extensions (`/detox`)**:
   - `/detox status`: Displays intercepted count, characters in/out, savings percentage, stored record count, and total database size in MB.
   - `/detox purge [days]`: Manually triggers unthrottled retention cleanup or purges records older than N days with detailed accounting.
5. **Hook Manifest Alignment**:
   - `plugin.yaml` `provides_hooks` and `__init__.py` `register(ctx)` strictly match 1:1:
     - `transform_tool_result`
     - `transform_terminal_output`
     - `on_session_reset`
   - All three hooks exist in `VALID_HOOKS` across both Hermes v0.19.0 and GitHub `main`.
6. **Security & Redaction Verification**:
   - Disclosed storage architecture: Local unencrypted SQLite database located at `%LOCALAPPDATA%/hermes-agent/plugins/hermes-detox/detox.db` (or `~/.hermes/plugin-data/hermes-detox/detox.db`).
   - Verified that while Detox preserves exact raw bytes in local SQLite for 100% reconstruction fidelity, Hermes Agent's outbound message sanitization pipeline (`agent.redact.redact_sensitive_text`) automatically redacts API keys and tokens (e.g. `sk-ant-api03-...`) before transmission to the model when `security.redact_secrets` is enabled.

---

## 2. Test Execution Results

Full test suite execution (`python -m unittest discover -s tests -p "test_*.py"`):
```
Ran 70 tests in 15.283s — OK
```

### Safety & Retention Suite (`tests/test_safety.py`)
| Test Case | Verification Target | Result |
|---|---|---|
| `test_concurrent_writes_wal_mode` | 10 concurrent threads inserting simultaneously into SQLite WAL; 0 deadlocks or lock errors | PASS |
| `test_age_based_retention_prune` | Accurate deletion of records older than 30 days while preserving newer records | PASS |
| `test_size_cap_retention_prune` | Sequential eviction of oldest records when store exceeds disk cap | PASS |
| `test_retention_throttling` | Repeated invocations within throttle window return `None` with zero redundant I/O | PASS |
| `test_redaction_behavior_with_secrets` | Local verbatim storage of `sk-ant-...` keys + verified outbound masking by Hermes | PASS |
| `test_excluded_tools_configuration` | Configured `excluded_tools` bypass firewall interception completely | PASS |
| `test_fail_open_on_corrupt_database` | Zero uncaught exceptions; returns `None` (fail-open) if database file is corrupt | PASS |
| `test_slash_command_purge_and_status` | `/detox purge` and `/detox status` return clean metrics including DB size in MB | PASS |

### Regression Suites
- `tests/test_core.py`: 17/17 PASS (50k+ untruncated capture, double-wrap guard, background process bypass, parallel terminal safety, line retrieval).
- `tests/test_extractors.py`: 45/45 PASS (JSON, tests, build logs, file trees, terminal output, ground-truth fidelity).

---

## 3. Pre-Deployment Security & Windows Storage Disclosure

- **Storage Location:** `%LOCALAPPDATA%\hermes-agent\plugins\hermes-detox\detox.db` (or `~/.hermes/plugin-data/hermes-detox/detox.db`).
- **File Permissions:** Created with directory permissions `0700` and file permissions `0600` on POSIX systems. On Windows NTFS systems, access is governed by the user profile ACL, accessible to the logged-in user and administrators. The SQLite database is **not** encrypted at rest.
- **Sensitive Data Handling:** Raw tool outputs (such as environment variable dumps, test runs containing credentials, or curl authorization headers) are stored in plaintext locally. Hermes Agent's outbound redaction pipeline masks credentials before sending them to external LLMs during `detox_inspect` calls, but users with access to the local filesystem can read the database directly.
