# Hermes Detox

**The Zero-Loss Diagnostic Firewall for Hermes Agent**  
*Eliminates 88% of tool noise while guaranteeing 100% preservation of errors, stack traces, and exit codes. Archives raw originals in local zero-network SQLite WAL for 0.16 ms surgical retrieval.*

[![License: MIT](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)
[![Dependencies: 0 external](https://img.shields.io/badge/dependencies-0%20external-success.svg)](#security--privacy)
[![Tests: 74/74 Passing](https://img.shields.io/badge/tests-74%2F74%20passing-brightgreen.svg)](#verification--test-suite)
[![Context Reduction: 88.3%](https://img.shields.io/badge/context%20reduction-88.3%25-blue.svg)](#empirical-benchmark)
[![Signal Preservation: 100%](https://img.shields.io/badge/signal%20preservation-100%25%20(28%2F28)-brightgreen.svg)](#empirical-benchmark)
[![Release: v0.1.0](https://img.shields.io/badge/release-v0.1.0-blue.svg)](https://github.com/kellycryptos/hermes-detox/releases/tag/v0.1.0)
[![Hermes Agent](https://img.shields.io/badge/hermes--agent-%3E%3D0.19.0-blueviolet.svg)](#compatibility)

---

## 90-Second Judge & Evaluator Quickstart

Evaluate Hermes Detox in under 90 seconds in any sterile environment:

```bash
# 1. Clone repository
git clone https://github.com/kellycryptos/hermes-detox.git
cd hermes-detox

# 2. Run the 74-test verification suite (executes in ~2.2s with 0 dependencies)
uv run python -m unittest discover -s tests -p "test_*.py" -v

# 3. Run the empirical 9-workload benchmark (evaluates 100% signal preservation & latencies)
uv run python benchmarks/run_benchmark.py

# 4. Run the Amputation Test (demonstrates why generic head/tail compressors fail)
uv run python scripts/demo_amputation_test.py
```

### The 10-Second Live Demonstration: The "Amputation Test"

In vanilla Hermes Agent and commodity compressors, outputs over 50,000 characters are capped to head 40% and tail 60%—**permanently destroying the middle lines where root cause errors live**.

Run the interactive Amputation Test:

```bash
uv run python scripts/demo_amputation_test.py
```

```
================================================================================
HERMES DETOX -- THE AMPUTATION TEST (Zero-Loss vs Lossy Compression)
================================================================================
Simulating a realistic 1,500-line test log (73,535 characters)
with a critical failure buried in the middle at Line 750...

[1] COMMODITY COMPRESSOR (Head/Tail Slicing)
• Delivered:       50,041 characters
• Root Cause:      [X] AMPUTATED (Permanently destroyed in middle)
• Agent Impact:    Model hallucinates or fails the task because Line 750 was erased.

[2] HERMES DETOX (Zero-Loss Diagnostic Firewall)
• Delivered:       1,492 characters (98.0% noise eliminated)
• Processing Time: 141.23 ms
• Root Cause:      [OK] PRESERVED (100% Critical Signal Retention)
• Evidence ID:     ev_9cd2cba85963 (Local SQLite WAL)

[3] SURGICAL ON-DEMAND RETRIEVAL (`detox_inspect`)
• Retrieval Time:  0.39 ms
• Retrieved Context:
  Line 0748: [DEBUG] worker-thread 4 heartbeat ack
  Line 0749: [DEBUG] worker-thread 5 heartbeat ack
  Line 0750: [ERROR] CRITICAL_EXCEPTION: Database pool exhausted at host 10.0.0.5:5432
  Line 0751: [DEBUG] worker-thread 7 heartbeat ack
  Line 0752: [DEBUG] worker-thread 0 heartbeat ack
================================================================================
VERDICT: Detox eliminates 98.0% of context noise without blinding the model.
================================================================================
```

---

## Sponsor Track & Evidence Matrix ("The Receipt Box")

Hermes Detox was engineered specifically for the **Hermes Agent Plugin Hackathon** (Nous Research). It deeply leverages the Hermes Agent Plugin SDK without monkey-patching or third-party dependencies:

| Hermes SDK Capability | Implementation File & Line Permalink | Functional Purpose in Hermes Detox |
|---|---|---|
| **`transform_terminal_output`** | [`__init__.py#L171-L257`](__init__.py) | Intercepts raw terminal stdout/stderr **before** Hermes's lossy 50,000-character middle truncation runs. |
| **`transform_tool_result`** | [`__init__.py#L44-L169`](__init__.py) | Intercepts all tool results before insertion into LLM conversation context; replaces noisy output with compact diagnostic reports. |
| **`on_session_reset`** | [`__init__.py#L279-L290`](__init__.py) | Observer hook to purge session evidence and execute throttled SQLite maintenance. |
| **`detox_inspect` Tool** | [`detox_tools/tool_inspect.py#L1-L60`](detox_tools/tool_inspect.py) | Custom agent tool allowing the LLM to pull exact 1-based line slices (`start_line`, `end_line`) in 0.16 ms. |
| **`detox_search` Tool** | [`detox_tools/tool_search.py#L1-L75`](detox_tools/tool_search.py) | Custom agent tool allowing the LLM to search archived outputs for regex or exact text patterns. |
| **`detox_status` Tool** | [`detox_tools/tool_status.py#L1-L50`](detox_tools/tool_status.py) | Custom agent tool providing session-level firewall statistics and character savings metrics. |
| **`/detox` Slash Command** | [`__init__.py#L291-L373`](__init__.py) | Interactive user command line interface supporting `/detox status`, `/detox inspect`, `/detox search`, and `/detox purge`. |
| **SQLite WAL Storage** | [`store.py#L32-L140`](store.py) | Re-entrant, multi-threaded storage using `PRAGMA journal_mode = WAL` under `<hermes_home>/plugin-data/hermes-detox/`. |
| **Declarative Manifest** | [`plugin.yaml#L1-L68`](plugin.yaml) | Declares tools, hooks, configuration schema, and SemVer compatibility (`requires_hermes: ">=0.19.0"`). |

---

## Why This Matters

Agents spend over 70% of their operational tokens reading raw tool output: failing test suites, compilation warnings, massive JSON payloads, and directory listings.

1. **Context Window Exhaustion:** A single un-truncated test failure or build log can dump 10,000–30,000 tokens into history, blowing past reasoning limits, degrading model attention, and forcing premature context compaction.
2. **The Hermes "Middle-Truncation" Trap:** In Hermes Agent 0.19.0+, terminal outputs exceeding 50,000 characters are capped to 40% head and 60% tail. The middle chunk is erased forever. If the assertion failure or stack trace sits in that middle block, the model is blind and cannot recover it.
3. **Token Noise Degradation:** Models perform worse when wading through thousands of passing test lines to find one missing bracket.

**Hermes Detox flips the equation: The model receives high-density diagnostic summaries. The complete original is preserved locally. Nothing is thrown away.**

---

## How It Works

```
                        [Tool Output Generated]
                  (Terminal, Pytest, Compiler, API)
                                  │
                                  ▼
                     [Detox Firewall Hook]
           (transform_terminal_output / transform_tool_result)
                                  │
           ┌──────────────────────┴──────────────────────┐
           │                                             │
      [Skip Path]                                   [Active Path]
  • Output <= 6,000 chars                       • Output > 6,000 chars
  • Excluded tool (patch, vision)               • Not media/base64
  • Detox self-tools (inspect, search)          • Valid payload
  • Media/data URI payload                               │
           │                                             ▼
           │                             1. Archive raw text in SQLite WAL
           │                             2. Run content-aware extractor
           │                             3. Build compact diagnostic report
           │                             4. Evaluate 0.55 compression gate
           │                                             │
           │                                    Passed   │   Failed (>55% size)
           │                                    Gate     │   (e.g. single giant line)
           │                                     │       └──> Fail-open untouched
           ▼                                     ▼
    [Pass Through]                     [Compact Report Delivered]
(Delivered to model untouched)        (Header + Summary + Errors + ID)
                                                 │
                                                 ▼
                                        [Agent Retrieval Loop]
                                      Agent calls detox_inspect()
                                      for exact lines in 0.16 ms
```

### The Compression Gate Guarantee

Detox enforces a hard safety gate (`max_ratio = 0.55`):
- A compact report is **only** delivered if its size is at most **55%** of the original output.
- If an output cannot be cleanly compressed (such as high-entropy binary text or unstructured single-line blobs), Detox **fails open** and delivers the original output untouched.
- If the SQLite database locks, disk fills up, or an unexpected exception occurs, Detox catches the error, logs a debug notice, and returns `None`—ensuring Hermes continues execution without crashing.

---

## Empirical Benchmark

Tested across 9 realistic developer workloads using [`benchmarks/run_benchmark.py`](benchmarks/run_benchmark.py).

*Baselines represent what Hermes delivers to the model without Detox. For terminal outputs over 50,000 characters, baseline is capped at the 50,000 characters Hermes normally provides. Token counts are estimated using the industry standard of $\text{chars} / 4$.*

| Workload Scenario | Captured Chars | Baseline Chars / Tokens | Delivered Chars / Tokens | Reduction | Critical Signals Preserved | Est. Tokens Saved | Transform Latency | Storage Round-Trip |
|---|---|---|---|---|---|---|---|---|
| **Pytest Test Suite** (3 fails, 42 pass) | 15,317 | 15,317 / 3,829 | 2,869 / 717 | **81.3%** | **6/6 (100%)** | **3,112** | 38.49 ms | **100% PASS (verbatim)** |
| **C++ Build Log** (GCC/Clang, 4 files) | 9,902 | 9,902 / 2,475 | 1,894 / 473 | **80.9%** | **6/6 (100%)** | **2,002** | 16.16 ms | **100% PASS (verbatim)** |
| **JSON API Payload** (50 nested records) | 29,923 | 29,923 / 7,480 | 1,973 / 493 | **93.4%** | **3/3 (100%)** | **6,987** | 23.83 ms | **100% PASS (verbatim)** |
| **Filesystem Listing** (580 files, tree) | 15,155 | 15,155 / 3,788 | 910 / 227 | **94.0%** | **4/4 (100%)** | **3,561** | 16.56 ms | **100% PASS (verbatim)** |
| **Server Trace Log** (420 lines) | 35,448 | 35,448 / 8,862 | 1,822 / 455 | **94.9%** | **4/4 (100%)** | **8,407** | 36.56 ms | **100% PASS (verbatim)** |
| **Massive Terminal Log** (>50k cap) | 106,913 | 50,000 / 12,500 | 1,487 / 371 | **97.0%** | **2/2 (100%)** | **12,129** | 131.26 ms | **100% PASS (verbatim)** |
| **Short Output Below Threshold** (<6k) | 1,095 | 1,095 / 273 | 1,095 / 273 | **0.0%** | **1/1 (100%)** | **0** | 0.01 ms | **Passthrough (untouched)** |
| **Low-Reducibility Payload** (0.55 gate) | 7,500 | 7,500 / 1,875 | 7,500 / 1,875 | **0.0%** | **1/1 (100%)** | **0** | 6.77 ms | **Passthrough (gate bypass)** |
| **Output with Secret Strings** (`sk-demo`) | 11,752 | 11,752 / 2,943 | 1,032 / 258 | **91.2%** | **1/1 (100%)** | **2,680** | 17.68 ms | **100% PASS (verbatim)** |
| **TOTAL / OVERALL** | **233,005** | **176,092 / 44,023** | **20,582 / 5,145** | **88.3%** | **28/28 (100.0%)** | **38,878** | **31.92 ms** | **100% Byte Fidelity** |

---

## Content-Aware Extractors

Detox features 6 specialized extractors with automatic heuristic dispatch:

| Extractor | Source File | Preservation Strategy & Capabilities |
|---|---|---|
| **Test Suites** | [`extractors/extract_tests.py`](extractors/extract_tests.py) | Parses Pytest, Unittest, Jest, Cargo test. Preserves pass/fail/skip tallies, failed test names, assertion messages, and failing file:line references. |
| **Compiler & Build Logs** | [`extractors/extract_build.py`](extractors/extract_build.py) | Parses GCC, Clang, Rustc, tsc. Captures compilation diagnostics with exact file/line, template error chains, and linker undefined references. |
| **Filesystem & Directory Trees** | [`extractors/extract_files.py`](extractors/extract_files.py) | Handles `find`, `ls -laR`, and `tree` outputs (including Unicode box drawings `├──`, `└──`). Pinpoints key configuration files (`package.json`, `tsconfig.json`, `.env.example`, `Cargo.toml`, `Dockerfile`) and folder distributions. |
| **JSON API Payloads** | [`extractors/extract_json.py`](extractors/extract_json.py) | Extracts schema skeleton, record count, top keys, and error payloads while keeping numeric IDs and key fields exact. |
| **Terminal & Shell Output** | [`extractors/extract_terminal.py`](extractors/extract_terminal.py) | Automatically handles commands matching `terminal`, `bash`, `shell`, `exec`, `cmd`, `run`, and `log`. Captures exit codes, stack traces, and unhandled exceptions. |
| **Plain Text Fallback** | [`extractors/extract_text.py`](extractors/extract_text.py) | Preserves Markdown headings and GitHub-style alert blocks (`[!NOTE]`, `[!WARNING]`, `[!CRITICAL]`). |

---

## What the Model Sees

Instead of 30,000 characters of noise, the LLM receives a clean, structured diagnostic report with exact 1-based line numbers:

```
[DETOX FIREWALL: Output intercepted and compressed]
Tool: terminal (`pytest tests/`) | Original: 15,317 chars (382 lines) | Report: 2,869 chars | Reduction: 81.3%
Evidence ID: ev_4f1b8a92e10c | Type: text/x-pytest

--- Extracted Summary ---
Test Suite: 42 passed, 3 failed, 0 skipped
Failing Tests:
  • tests/test_auth.py::test_jwt_expiration (line 142)
  • tests/test_billing.py::test_invoice_calc (line 218)
  • tests/test_api.py::test_rate_limit_exceeded (line 305)

--- Errors & Warnings ---
[Line 142] AssertionError: Expected token expiry 3600 but got 0
[Line 218] KeyError: 'tax_rate'
[Line 305] HTTPError: 429 Too Many Requests

--- Head Preview (Lines 1-5) ---
1 | ============================= test session starts ==============================
2 | platform linux -- Python 3.13.1, pytest-8.3.2, pluggy-1.5.0
3 | rootdir: /home/user/workspace
4 | collected 45 items
5 | 

--- Tail Preview (Lines 378-382) ---
378 | =========================== short test summary info ============================
379 | FAILED tests/test_auth.py::test_jwt_expiration - AssertionError: Expected...
380 | FAILED tests/test_billing.py::test_invoice_calc - KeyError: 'tax_rate'
381 | FAILED tests/test_api.py::test_rate_limit_exceeded - HTTPError: 429...
382 | ========================= 3 failed, 42 passed in 1.42s =========================

To inspect exact lines around failures, call:
detox_inspect(evidence_id="ev_4f1b8a92e10c", start_line=135, end_line=150)
```

Line numbers match the stored original byte-for-byte. The agent can immediately call `detox_inspect` with the provided evidence ID.

---

## Agent Tools & Interactive Retrieval

Hermes Detox exposes three tools to the agent:

### 1. `detox_inspect`
Retrieves exact 1-based line ranges from stored outputs in **0.16 ms**:

```json
{
  "evidence_id": "ev_4f1b8a92e10c",
  "start_line": 138,
  "end_line": 146
}
```

### 2. `detox_search`
Searches archived outputs for regex or exact string matches:

```json
{
  "query": "KeyError: 'tax_rate'",
  "evidence_id": "ev_4f1b8a92e10c",
  "max_results": 5
}
```

### 3. `detox_status`
Reports current session firewall statistics and token savings.

*Note: Detox self-tools are automatically excluded from firewall interception, ensuring long inspect results reach the model intact.*

---

## User Slash Commands

Users can inspect and monitor the firewall directly from the Hermes chat prompt:

| Command | Action |
|---|---|
| `/detox status` | Shows total outputs intercepted, characters in/out, savings %, database size, and record count. |
| `/detox inspect <id> [start] [end]` | Displays formatted, numbered lines directly in the terminal interface. |
| `/detox search <phrase> [id]` | Searches stored evidence for specific strings or error codes. |
| `/detox purge [days]` | Runs maintenance cleanup or purges evidence older than $N$ days. |

---

## Installation & Configuration

### Install

Install via the Hermes Agent plugin manager:
```bash
hermes plugins install kellycryptos/hermes-detox
hermes plugins enable hermes-detox
```

Or clone into your local Hermes plugins folder:
```bash
git clone https://github.com/kellycryptos/hermes-detox.git ~/.hermes/plugins/hermes-detox
hermes plugins enable hermes-detox
```

Verify loading in your next Hermes session with `/detox status`.

### Configuration (`plugin.yaml`)

| Option | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `true` | Master switch for Detox firewall interception. |
| `min_size` | `int` | `6000` | Minimum character threshold before compression triggers. |
| `max_report_chars` | `int` | `3000` | Maximum character budget allocated for compact reports. |
| `max_ratio` | `float` | `0.55` | Compression safety gate (report / original). Fails open if above. |
| `head_lines` | `int` | `5` | Leading lines previewed in report. |
| `tail_lines` | `int` | `5` | Trailing lines previewed in report. |
| `excluded_tools` | `list` | `[browser_vision, patch, write_file, ...]` | Tools exempted from interception (vision, media, file writes). |
| `retention_days` | `int` | `30` | Retention window for archived evidence. |
| `max_store_size_mb` | `int` | `100` | Maximum SQLite database size before LRU eviction. |
| `debug` | `bool` | `false` | Enable verbose diagnostic logging. |

---

## Security & Privacy

- **Zero External Dependencies:** Built entirely with the Python standard library (`sqlite3`, `re`, `json`, `dataclasses`). No vulnerable supply chain vectors.
- **Strictly Local Storage:** No telemetry, no cloud relays, no outbound network requests. All evidence stays on your host machine:
  - **Linux/macOS:** `~/.hermes/plugin-data/hermes-detox/detox.db` (created with `0700` directory and `0600` file permissions).
  - **Windows:** `%LOCALAPPDATA%\hermes\plugin-data\hermes-detox\detox.db` (protected by user profile ACLs).
- **Secret Redaction Compliance:** Raw outputs are stored locally verbatim to preserve accurate stack traces. When the agent retrieves lines via `detox_inspect`, Hermes's standard outbound secret redaction pipeline (`security.redact_secrets`) applies before tokens are dispatched to the LLM.
- **Fail-Open Resilience:** Storage write failures, database locks, or parser errors never block tool execution or crash Hermes.

---

## Verification & Test Suite

Hermes Detox includes a comprehensive test suite of 74 unit, integration, and safety tests:

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

- **`tests/test_core.py` (17 tests):** Threshold bounding, fail-open paths, self-exclusion, un-truncated 50k+ terminal recovery, parallel terminal concurrency, and double-wrap prevention.
- **`tests/test_extractors.py` (45 tests):** Pytest, GCC/Clang, JSON, filesystem trees, server logs, and 6 ground-truth line-fidelity verification tests.
- **`tests/test_safety.py` (12 tests):** 10-thread SQLite WAL stress testing, age-based retention, disk size cap pruning, post-compaction session rotation, media payload bypass, and database corruption recovery.

---

## Compatibility

- Requires **Hermes Agent $\ge 0.19.0$**.
- Fully compatible with Python 3.10, 3.11, 3.12, and 3.13.
- Tested and verified on Windows, macOS, and Linux.

---

## License

MIT © [kellycryptos](https://github.com/kellycryptos). See [LICENSE](LICENSE).
