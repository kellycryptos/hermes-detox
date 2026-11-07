# Hermes Detox

> **Tool Output Firewall & Context Compressor for Hermes Agent**  
> Intercepts noisy, oversized tool results before they flood LLM context, compresses them into structured diagnostic summaries, archives the raw originals in local SQLite storage, and provides loss-free line retrieval on demand.

[![Tests](https://img.shields.io/badge/tests-73%2F73%20passing-brightgreen)](#test-suite)
[![Reduction](https://img.shields.io/badge/token%20reduction-88.2%25%20(est)-blue)](#benchmark-results)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20external-success)](#zero-dependency-design)
[![License](https://img.shields.io/badge/license-MIT-purple)](#license)

---

## The Problem

Agentic workflows generate massive tool outputs: verbose pytest runs, endless compiler diagnostics, huge JSON API payloads, and 1,000-line directory trees.
1. **Context Exhaustion:** A single un-truncated test failure can consume 10,000–30,000 tokens, degrading model reasoning and forcing premature context compaction.
2. **Hermes's Lossy Inline Truncation:** Standard Hermes truncates terminal output exceeding 50,000 characters by keeping 40% head and 60% tail—permanently destroying the critical middle lines where root cause errors often reside.
3. **Noisy Distraction:** LLMs waste reasoning tokens filtering thousands of passing lines instead of zeroing in on actionable stack traces.

---

## How It Works

Hermes Detox is a zero-dependency plugin that sits between Hermes tool execution and model context:

```
[Tool Execution] (terminal, pytest, compiler, etc.)
       │
       ▼
[Detox Firewall Hook] (transform_terminal_output / transform_tool_result)
       ├──> Output <= 6,000 chars? ──────> [Pass Through Untouched]
       ├──> Vision / Media Payload? ─────> [Pass Through Untouched]
       │
       └──> Output > 6,000 chars?
              ├──> 1. Store Raw Original in Local SQLite WAL (`detox.db`)
              ├──> 2. Run Content-Aware Extractor (JSON, Pytest, Build, Tree)
              ├──> 3. Generate Compact Diagnostic Report (<55% original size)
              └──> 4. Return Report to LLM with Evidence ID for Line Inspection
```

When the agent needs specific lines or context around a stack trace, it calls `detox_inspect(evidence_id, start_line, end_line)` to pull exact lines from local storage in **0.16 ms**.

---

## Benchmark Results

Evaluated across 9 realistic developer workloads via [benchmarks/run_benchmark.py](benchmarks/run_benchmark.py).  
*Token counts are estimated using the standard approximation of `chars / 4`.*

| Workload Scenario | Captured Size | Baseline Size (chars / tokens est) | Delivered Size (chars / tokens est) | Reduction (%) | Estimated Tokens Saved | Transform Latency | Inspect Latency | Storage Round-Trip |
|---|---|---|---|---|---|---|---|---|
| **Pytest Test Suite** (3 fails, 42 pass) | 15,317 | 15,317 / 3,829 | 2,869 / 717 | **81.3%** | **3,112** | 56.16 ms | 0.16 ms | **PASS (verbatim)** |
| **C++ Build Log** (GCC/Clang, 4 files) | 9,902 | 9,902 / 2,475 | 1,894 / 473 | **80.9%** | **2,002** | 4.01 ms | 0.14 ms | **PASS (verbatim)** |
| **JSON API Payload** (50 records) | 29,923 | 29,923 / 7,480 | 1,973 / 493 | **93.4%** | **6,987** | 6.82 ms | 0.12 ms | **PASS (verbatim)** |
| **Filesystem Listing** (580 files, tree) | 15,155 | 15,155 / 3,788 | 671 / 167 | **95.6%** | **3,621** | 12.33 ms | 0.13 ms | **PASS (verbatim)** |
| **Server Trace Log** (420 lines) | 35,448 | 35,448 / 8,862 | 2,425 / 606 | **93.2%** | **8,256** | 25.15 ms | 0.15 ms | **PASS (verbatim)** |
| **Massive Terminal Log** (>50k cap) | 106,913 | 50,000 / 12,500 | 1,341 / 335 | **97.3%** | **12,165** | 41.74 ms | 0.18 ms | **PASS (verbatim)** |
| **Short Output Below Threshold** (<6k) | 1,095 | 1,095 / 273 | 1,095 / 273 | **0.0%** | **0** | 0.01 ms | 0.00 ms | **N/A (passthrough)** |
| **Low-Reducibility Payload** (0.55 gate) | 7,500 | 7,500 / 1,875 | 7,500 / 1,875 | **0.0%** | **0** | 2.77 ms | 0.00 ms | **N/A (gate bypass)** |
| **Output with Secret Strings** (`sk-ant-`) | 11,775 | 11,775 / 2,943 | 1,055 / 263 | **91.0%** | **2,680** | 9.07 ms | 0.17 ms | **PASS (verbatim)** |
| **TOTAL / OVERALL** | **233,028** | **176,115 / 44,025** | **20,823 / 5,202** | **88.2%** | **38,823** | **17.56 ms** | **0.16 ms** | **100% (7/7 PASS)** |

*Note on Massive Terminal Output: Standard Hermes enforces a lossy inline cap of 50,000 characters before model delivery (discarding lines 40%–60%). Baseline is evaluated against this 50,000-character ceiling, while Detox captured the full 106,913 characters un-truncated in SQLite, allowing verbatim recovery of middle line 750.*

---

## Quick Start

### Installation

Install directly via Hermes Agent plugin manager:
```bash
hermes plugins install kellycryptos/hermes-detox
```

Or clone into your local Hermes plugins directory:
```bash
git clone https://github.com/kellycryptos/hermes-detox.git ~/.hermes/plugins/hermes-detox
hermes plugins enable hermes-detox
```

### Slash Commands

Monitor and control the firewall directly in chat:
- `/detox status` — View total intercepted outputs, characters saved, database size, and record counts.
- `/detox inspect <evidence_id> [start] [end]` — Inspect exact lines from stored evidence.
- `/detox search <phrase> [evidence_id]` — Search stored tool outputs for text or error codes.
- `/detox purge [days]` — Run retention pruning or purge outputs older than N days.

---

## Agent Tools

Hermes Detox automatically registers three tools available to the model:

### `detox_inspect`
Retrieve exact lines from an archived tool output:
```json
{
  "evidence_id": "ev_4f1b8a92e10c",
  "start_line": 40,
  "end_line": 55
}
```

### `detox_search`
Search archived tool outputs for regex or text matches:
```json
{
  "query": "NullPointerException",
  "evidence_id": "ev_4f1b8a92e10c",
  "max_results": 10
}
```

### `detox_status`
Query session firewall statistics and token savings.

---

## Configuration

Settings are declared in `plugin.yaml` and configurable via Hermes Agent configuration:

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `boolean` | `true` | Master switch for Detox firewall interception. |
| `min_size` | `integer` | `6000` | Minimum character threshold before compression triggers. |
| `max_report_chars` | `integer` | `3000` | Maximum character budget allocated for compact reports. |
| `max_ratio` | `float` | `0.55` | Max compression ratio (report / original). Fails open if report exceeds 55% of original. |
| `head_lines` | `integer` | `5` | Number of leading lines in preview report. |
| `tail_lines` | `integer` | `5` | Number of trailing lines in preview report. |
| `excluded_tools` | `array` | `[browser_vision, browser_snapshot, image_generate, video_generate, video_analyze, vision_analyze, text_to_speech, patch, write_file]` | Tool names exempted from Detox firewall interception. Defaults to vision, media, and file editing tools. |
| `retention_days` | `integer` | `30` | Number of days to retain stored evidence before pruning. |
| `max_store_size_mb` | `integer` | `100` | Disk cap in megabytes before oldest evidence records are evicted. |
| `debug` | `boolean` | `false` | Enable verbose logging for Detox operations. |

---

## Architecture & Guarantees

1. **Zero External Dependencies:** Built 100% on the Python standard library (`sqlite3`, `re`, `json`, `dataclasses`).
2. **Concurrent Safety:** Uses SQLite in `WAL` (Write-Ahead Logging) mode with `NORMAL` synchrony and re-entrant connection pooling. Safe across multi-threaded agent runs.
3. **Fail-Open Resilience:** If storage writes fail (disk full, permission error, corrupt database), Detox logs the error and returns `None`—letting Hermes deliver the original un-truncated output without crashing.
4. **Self-Exclusion Guard:** Detox's own inspection tools (`detox_inspect`, `detox_search`, `detox_status`) are hard-coded to bypass interception, preventing recursion loops.
5. **Media & Vision Protection:** Data URIs (`data:image/`, `data:video/`, `data:audio/`) and raw base64 streams bypass compression automatically.
6. **Double-Wrap Guard:** Inspects output banners to ensure already-transformed reports are never compressed a second time.
7. **Background Process Bypass:** Terminal lifecycle notifications (`returncode is None` and empty `env_type`) bypass evidence archiving.
8. **Throttled Retention:** Retention pruning runs at session reset or manual `/detox purge`, throttled to at most once every 6 hours—never during tool execution.

---

## Security, Privacy & Local Storage Disclosure

- **Storage Location:** Evidence records are stored in a local SQLite database at:
  - **Windows:** `%LOCALAPPDATA%\hermes\plugin-data\hermes-detox\detox.db`
  - **POSIX (Linux/macOS):** `~/.hermes/plugin-data/hermes-detox/detox.db`
- **File Permissions:** Created with directory mode `0700` and file mode `0600` on POSIX systems. On Windows NTFS systems, access is restricted by standard Windows User Profile ACLs (accessible to the logged-in user and administrators).
- **Unencrypted at Rest:** Stored tool outputs are **not** encrypted on disk. If tool outputs contain secrets, environment dumps, or private tokens, they reside unencrypted in `detox.db`.
- **Outbound Redaction:** While Detox stores raw outputs verbatim for accurate debugging, secrets returned by `detox_inspect` may be masked before the model sees them depending on Hermes's `security.redact_secrets` setting (which runs `agent.redact.redact_sensitive_text` on outbound messages).

---

## Known Limitations

1. **Compaction Session Rotation:** In order to maintain compatibility with Hermes 0.19.0, `post_compaction` is not registered in `provides_hooks`. If Hermes rotates session IDs during context compaction, evidence records stored prior to compaction become inaccessible to session-scoped `detox_inspect` calls unless relinked via `store.relink_session()` or accessed via global `/detox` slash commands.
2. **Deterministic Storage Round-Trip vs. Agent Performance:** The benchmark verifies 100% byte-for-byte fidelity of line storage and retrieval ("Storage Round-Trip"). It does not evaluate model task success rates or agent reasoning accuracy, which depend on model capabilities and task context.
3. **Single-Line Unstructured Payloads:** Massive single-line payloads without line breaks are caught by the 0.55 compression ratio gate and delivered untouched, as line-based extraction cannot safely reduce them.

---

## Verification & Test Suite

The test suite covers 73 automated tests with 100% pass rate:
```bash
uv run --with hermes-agent python -m unittest discover -s tests -p "test_*.py" -v
```

- **`tests/test_core.py`** (17 tests): Interception threshold, fail-open paths, self-exclusion, 50k+ untruncated recovery, parallel terminal safety, double-wrap guards.
- **`tests/test_extractors.py`** (45 tests): JSON, pytest, compiler logs, file listings, terminal output, and 6 ground-truth line-fidelity tests.
- **`tests/test_safety.py`** (11 tests): 10-thread WAL concurrency, age-based retention, disk size cap pruning, throttled cleanup, post-compaction session rotation, media bypass, default exclusions, secret redaction, and database corruption recovery.

---

## License

MIT © [kellycryptos](https://github.com/kellycryptos)
