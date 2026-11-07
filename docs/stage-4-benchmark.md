# Stage 4 Benchmark Report: Performance, Token Reduction & Fidelity

**Status:** COMPLETE & BENCHMARKED  
**Benchmark Suite:** `benchmarks/run_benchmark.py`  
**Raw Results:** `docs/benchmark_results.json`  
**Overall Character Reduction:** **94.7%**  
**Estimated Tokens Saved:** **50,371 tokens** across 6 developer scenarios  
**Average Transformation Overhead:** **18.77 ms**  
**Average Inspection Retrieval Overhead:** **0.15 ms**  
**Ground-Truth Line Fidelity:** **100% (6/6 scenarios recovered verbatim)**  

---

## 1. Methodology & Test Setup

- **Baseline:** Standard Hermes Agent execution with Detox inactive (or Hermes inline terminal cap at 50,000 characters where the middle 40-60% slice is permanently discarded).
- **Environment:**
  - Python 3.13.13 (x86_64) on Windows NTFS
  - Hermes Agent v0.19.0 runtime
  - SQLite 3 with Write-Ahead Logging (WAL) and memory-mapped indexes
  - Zero external dependencies (stdlib only)
- **Token Estimation Formula:** Standard LLM tokenizer approximation ($\text{chars} / 4$).
- **Latency Measurement:** High-resolution monotonic timers (`time.perf_counter_ns()`) measuring end-to-end hook execution and SQLite retrieval.

---

## 2. Benchmark Results Matrix

| Scenario | Original (chars / tokens) | Detox Report (chars / tokens) | Reduction (%) | Tokens Saved | Transform Latency | Inspect Latency | Exact Line Fidelity |
|---|---|---|---|---|---|---|---|
| **Pytest Test Suite** (3 fails, 42 pass) | 15,317 / 3,829 | 2,869 / 717 | **81.3%** | **3,112** | 19.95 ms | 0.16 ms | **PASS** (100%) |
| **C++ Build Log** (GCC/Clang, 4 files) | 9,902 / 2,475 | 1,894 / 473 | **80.9%** | **2,002** | 10.01 ms | 0.14 ms | **PASS** (100%) |
| **JSON API Payload** (50 records, metadata) | 29,923 / 7,480 | 1,973 / 493 | **93.4%** | **6,987** | 5.79 ms | 0.12 ms | **PASS** (100%) |
| **Filesystem Listing** (580 files, tree) | 15,155 / 3,788 | 671 / 167 | **95.6%** | **3,621** | 14.23 ms | 0.13 ms | **PASS** (100%) |
| **Server Trace Log** (420 lines, traceback) | 35,448 / 8,862 | 2,425 / 606 | **93.2%** | **8,256** | 23.56 ms | 0.15 ms | **PASS** (100%) |
| **Massive Terminal Output** (>50k limit) | 106,913 / 26,728 | 1,341 / 335 | **98.7%** | **26,393** | 39.08 ms | 0.18 ms | **PASS** (100%) |
| **TOTAL / AVERAGE** | **212,658 / 53,162** | **11,173 / 2,791** | **94.7%** | **50,371** | **18.77 ms** | **0.15 ms** | **100%** |

---

## 3. Key Findings & Architectural Validation

### 1. Token Economy & Context Preservation
Across the six standard tool scenarios, Detox compressed **212,658 characters of raw developer output into 11,173 characters**, preventing context blowup while saving an estimated **50,371 tokens**. For long-running agent workflows involving repeated test/build cycles, this keeps conversation context windows uncluttered and prevents premature context truncation.

### 2. Solving Hermes's 50,000-Character Truncation Barrier
In standard Hermes, any terminal command generating over 50,000 characters is subjected to inline truncation keeping only the first 20,000 (40%) and last 30,000 (60%) characters—permanently losing anything in between.
- In Scenario 6 (106,913 characters across 1,500 lines), line 750 (byte position ~53,400) would have been destroyed.
- With Detox's early `transform_terminal_output` hook, the complete 106k payload was stored in SQLite before truncation. Calling `detox_inspect(evidence_id, 750, 750)` retrieved line 750 in **0.18 ms with 100% byte fidelity**.

### 3. Negligible Runtime Overhead
- Transformation latency averaged **18.77 ms**, well within the sub-50ms operational budget.
- Retrieval via `detox_inspect` averaged **0.15 ms**, enabled by indexed 1-based line slicing in SQLite.
