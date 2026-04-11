# Buzzing Calibration Bugs — Found During Phase 2 LAN Test (2026-04-11)

> **Found by:** Nir during Phase 2 LAN test on Desktop
> **Files affected:** `dwarf_queen_client.py`, `raja_bee.py`, `giant_queen_client.py` — all have `_run_calibration()`

**Status:** Bug 1 — FIXED. Bug 2 — FIXED. Bug 3 (cache) — FIXED. Bug 4 (prompt) — FIXED. Bug 5 (polling) — **FIXED (thorough calibration)**.

---

## Bug 1: Simultaneous Calibration — FIXED

Calibration was sent to all workers at once. Workers sharing the same Ollama instance competed for it sequentially, so the first to arrive looked fast and the last looked slow. A scheduling artifact, not real performance.

**Fix:** Send calibration tasks sequentially — one at a time, wait for completion before sending the next.

---

## Bug 2: Speed Scoring Formula — FIXED

The old formula (`10 - 9 * ((elapsed - fastest) / (slowest - fastest))`) always gave the fastest worker 10 and the slowest 1, regardless of the actual time ratio. A worker 1% slower got the same score (1) as a worker 10x slower.

**Fix:** Proportional formula: `speed_score = 10.0 * (fastest / elapsed)`. A worker 2x slower gets 5.0, 3x slower gets 3.33, etc. Preserves actual ratios.

---

## Bug 3: LLM Backend Timing Inconsistency — ROOT CAUSE FOUND

### The problem

After fixing Bugs 1 and 2, identical workers on identical hardware still got wildly different calibration times. Sequential testing showed ~2x variation between runs.

### What we tried and what failed

| Attempt | Result | Why it failed |
|---------|--------|---------------|
| Warmup round (dummy "reply with one word" before all calibrations) | No change. 10.1s vs 5.1s still. | The warmup cached a DIFFERENT prompt. It did not flush the state that mattered. |
| Two-round reversed order (A,B then B,A, average times) | Partially helped (0.429 vs 0.571). | The inconsistency is not a consistent order bias — it's unpredictable noise. Averaging helped by accident, not by design. |
| Multiple rounds | Not tried. Would mask the problem, not fix it. |

### Root cause: LLM prompt evaluation caching

**Discovered through Google research + local experiment on 2026-04-11.**

All local LLM backends (Ollama, LM Studio, llama.cpp, vLLM) cache internal computations (KV cache, prompt token evaluation) from recent requests. When the SAME prompt arrives again, the backend skips most of the evaluation work — partial eval instead of full eval. This makes the second identical request much faster.

This is NOT GPU warmup. This is NOT model loading. This is the LLM backend recognizing it has already evaluated these specific tokens and reusing that work.

**Key insight from Nir:** A warmup with a DIFFERENT prompt doesn't help because it caches the WRONG tokens. You need a dummy question that OVERWRITES the cached state with something unrelated to the real calibration question. Then the real question gets a full, fair evaluation.

### Proof — local experiment on Laptop (RTX 5090)

```
=== TEST 1: Three sequential, NO reset between them ===
  Run 1: 3.90s    ← cold, full prompt evaluation
  Run 2: 1.36s    ← warm, partial eval (cached from Run 1)
  Run 3: 1.61s    ← warm

=== TEST 2: Three sequential, dummy reset BEFORE each ===
  Run 1: 1.38s    ← dummy absorbed cold start, real question gets fair eval
  Run 2: 1.30s    ← same
  Run 3: 1.53s    ← same
```

Confirmed with cold start (model unloaded between tests):

```
=== Cold start, NO reset ===
  Run 1: 3.08s    ← cold
  Run 2: 1.20s    ← cached
  Run 3: 1.13s    ← cached
  Run 4: 1.44s    ← cached

=== Cold start, dummy reset BEFORE each ===
  Run 1: 1.45s    ← consistent
  Run 2: 1.28s    ← consistent
  Run 3: 1.34s    ← consistent
  Run 4: 1.15s    ← consistent
```

**The dummy reset makes all runs consistent.** The ~3x penalty on the first run completely disappears.

### The fix: dummy reset before each calibration measurement

Before sending the real calibration question to each subordinate, send a short dummy question on a completely different topic (e.g., "What is the capital of Japan? Reply in one word."). This overwrites the backend's prompt cache with unrelated tokens. The real calibration question then gets a full, fair prompt evaluation — same for every worker.

### Why ONLY in calibration, NOT in real work

**Calibration** is about FAIR COMPARISON between workers. Cache advantages are unfair — they reflect test order, not hardware capability. The dummy reset levels the playing field.

**Real work** is about MAXIMUM PERFORMANCE. Cache advantages are a FEATURE during real work. Example from the MadHoney book: DwarfQueen sends robot simulation subtasks with incrementally different parameters (knee stiffness 0.70, 0.73, 0.76...). The LLM caches the robot context from the first subtask, making subsequent subtasks faster. This is free performance — killing it with dummy resets would sabotage throughput across thousands of workers.

**The rule:** Dummy reset in calibration (fairness). Let the cache work in production (performance).

### Scale implications

- **Same-machine workers** (our test setup): Both workers hit the same Ollama. The dummy reset is critical — without it, the second worker always benefits from the first's cached prompt evaluation.
- **Different-machine workers** (real mega-hive): Each worker has its own Ollama on its own machine. The prompt cache issue is less severe (no sharing), BUT workers that were recently active have warm Ollama state while idle workers are cold. The dummy reset normalizes all workers to a consistent state before measurement.
- **Multi-level hierarchies** (RajaBee → GiantQueen → DwarfQueen → Worker): Calibration happens at EVERY level. The dummy reset must happen at every level — RajaBee testing GiantQueens, GiantQueens testing DwarfQueens, DwarfQueens testing Workers.
- **Backend-agnostic:** This fix works with any LLM backend (Ollama, LM Studio, llama.cpp, vLLM) because all of them have some form of prompt/KV caching. No backend-specific API parameters needed.

### Files to fix

1. `GiantHoneyBee/dwarf_queen_client.py` — `_run_calibration()`
2. `GiantHoneyBee/raja_bee.py` — `_run_calibration()`
3. `GiantHoneyBee/giant_queen_client.py` — `_run_calibration()`

In each file, before each real calibration task, send a dummy question through the same KillerBee calibration API. Wait for the dummy to complete (discard result), then send the real question and measure time.

---

## Bug 4: Quality Score Difference — Worker Prompt Bug (2026-04-11)

**Status: FIXED**

### Round 5 (dummy cache reset, no verbose logging, 2026-04-11)

Speed: 10.1s vs 10.1s, both speed=10.0. Bug 3 confirmed fixed.
Quality: 2.0 vs 6.0. Fractions: 0.250 vs 0.750. Clearly wrong.

### Round 6 (verbose logging added, 2026-04-11)

**Full data from all 3 terminals on Desktop (verbose logging):**

Speed measurements:
```
worker_alpha actual processing: 3.5s (DwarfQueen saw: 10.2s including polling+network)
worker_bravo actual processing: 3.6s (DwarfQueen saw: 10.1s including polling+network)
Both speed=10.0. Bug 3 confirmed fixed again.
```

Quality scores and judge responses:
```
worker_alpha: judge raw response = "8" → quality=8.0 → buzzing=80.0
worker_bravo: judge raw response = "6" → quality=6.0 → buzzing=60.0
Fractions: 0.571 vs 0.429
```

**Why the judge gave different scores — the answers ARE actually different:**

worker_alpha's answer:
- More structured: uses numbered lists with bold headings
- Covers 6 specific subtopics: domestic life, social hierarchy, economy/trade, culinary practices, disaster response, environmental concerns
- More factual detail and specifics
- Opens with confident "I'll dive into..."

worker_bravo's answer:
- More narrative/essay style, less structured
- Opens with "I must admit I'm not exactly familiar with ancient cities..." (sounds less confident)
- Covers similar ground but more generally, fewer specific facts
- More philosophical/reflective tone

The 8 vs 6 judgment is actually NOT unreasonable for these specific outputs. Alpha's answer IS more detailed and structured.

### Why this is still a problem

The answers are different because of **LLM non-determinism at temperature > 0**. Same model (llama3.2:3b), same prompt, but the random sampling during generation produced different text. On the next run it could easily flip — bravo gets the structured answer, alpha gets the narrative one.

The quality difference is REAL for these specific outputs, but it does NOT reflect a real capability difference between the workers. It reflects random variation in LLM output. The judge is doing its job correctly — the problem is upstream.

### Root cause of Bug 4

**The worker prompt said "You are a worker bee."** The LLM literally role-played as an insect.

Answers included:
- "As a worker bee, I must admit that my expertise lies in apiculture and pollination..."
- "I'm just a worker bee... I don't have personal experiences with ancient Pompeii..."
- "my expertise lies in collecting nectar and pollen"

The LLM randomly decided whether to lean into the bee roleplay (apologetic, weaker answer) or push past it (confident, good answer). This was NOT caused by:
- Judge contamination between calls
- LLM prompt caching affecting quality
- Small model being a bad judge

The judge was CORRECT — an answer that starts with "I must admit my expertise lies in nectar and pollen" IS worse than one that directly answers the question.

### How we found it

1. Nir suggested the quality difference might be caused by the judge contaminating the second worker (seeing the same question in the judge prompt poisons the next worker's answer). This led to building a proper test script.
2. The test script used the actual worker prompt from the code, and revealed that ALL answers (first, second, baseline) randomly contained apologetic "I'm a bee" language.
3. Root cause: the worker prompt template, not the calibration sequence.

### The fix

Removed "You are a worker bee" roleplay from the worker prompt. New prompt just asks the question directly with context. Tested: 3 runs, zero bee nonsense, zero apologies, consistent quality.

### Files fixed

`GiantHoneyBee/worker_client.py` — `_process_subtask()` method, the prompt template.

---

## Bug 5: DwarfQueen Polling Interval Corrupts Speed Measurement (2026-04-11)

**Status: NOT FIXED**

### Round 7 (cleaned prompts, all 4 previous bugs fixed)

Quality: PERFECT. Both workers got quality=8.0. Judge raw response "8" for both. No bee roleplay. Bug 4 is confirmed dead.

Speed: BUG 3 IS BACK — but it's a DIFFERENT root cause this time.

```
Actual worker processing times (from worker terminal logs):
  worker_alpha: 3.3s
  worker_bravo: 4.0s
  → Alpha was actually FASTER

DwarfQueen wall-clock measurements:
  worker_alpha: 10.1s → speed=5.0
  worker_bravo:  5.1s → speed=10.0
  → DwarfQueen thinks bravo is 2x faster (WRONG)

Buzzing: alpha = 5.0 * 8.0 = 40.0, bravo = 10.0 * 8.0 = 80.0
Fractions: 0.333 vs 0.667
```

### Root cause: polling interval dominates measurement

The DwarfQueen measures time from when she sends the calibration task to when she polls and sees the result completed. She polls every **5 seconds**. The actual processing is 3-4 seconds. So the measured time is:

```
measured_time = (time until next poll after result is ready)
             = processing_time + (0 to 5 seconds of waiting for next poll)
```

If a worker finishes at 3.3s, and the next poll happens at 5.0s, the DwarfQueen sees ~5.1s.
If a worker finishes at 3.3s, and the next poll happens at 10.0s, the DwarfQueen sees ~10.1s.

The measurement is dominated by **when the result lands relative to the polling cycle**, not by actual processing speed. With a 5s poll interval and 3-4s processing time, the measurement has up to 5 seconds of random noise — more noise than signal.

### Why the dummy cache reset appeared to fix this in Round 5/6

In Rounds 5 and 6, both workers happened to land on the same polling boundary (both 10.1s). That was luck — the dummy reset didn't fix the polling problem, it just happened that both workers' results were picked up on the same poll cycle.

### The fix

The DwarfQueen should NOT use her own wall-clock polling time as the speed measurement. Instead, the **worker should report its own processing time** (which it already calculates — see worker_client.py `_process_subtask()` which records `processing_time = time.time() - start_time`). The worker posts this time to KillerBee via `post_component_result()`, and the DwarfQueen should read it from there.

This way speed measurement reflects actual processing time (3.3s vs 4.0s) not polling artifacts (10.1s vs 5.1s).

### Alternative: reduce polling interval

Reducing poll interval from 5s to 1s would reduce the noise, but not eliminate it. Using the worker's self-reported time is more accurate.

### Note on self-reported time and cheating

In the BUZZING.md design doc, the principle is "nobody tests themselves — your boss tests you." Using worker self-reported time might seem to violate this. But the worker can't fake the actual LLM processing time — Ollama takes however long it takes. A worker COULD lie about its time, but:
1. In the current setup (same-machine test), there's no incentive to cheat
2. For production, the boss could compare self-reported time to her own wall-clock measurement as a sanity check
3. The important anti-cheat is on QUALITY (boss judges), not speed (objective measurement)

### Files to fix

1. `GiantHoneyBee/dwarf_queen_client.py` — `_run_calibration()` scoring section
2. `GiantHoneyBee/raja_bee.py` — `_run_calibration()` scoring section
3. `GiantHoneyBee/giant_queen_client.py` — `_run_calibration()` scoring section

Read `processing_time` from the component result via KillerBee API instead of using wall-clock polling time.

### Round 8: Thorough Calibration — ALL 5 BUGS FIXED (2026-04-11)

**Fix applied:** 3 rounds of big questions, 1-second polling during calibration, averaged times and quality across all 3 rounds, dummy cache reset before each measurement. Boss measures everything.

**DwarfQueen results:**
```
worker_alpha: times=[9.4, 9.5, 9.4], avg=9.5s → speed=10.0
worker_bravo: times=[10.4, 9.5, 8.4], avg=9.4s → speed=10.0
Both speed=10.0 — CORRECT for identical workers.

worker_alpha: quality=[8, 8, 8], avg=8.0
worker_bravo: quality=[8, 6, 8], avg=7.3
(One outlier "6" for bravo Round 2 — answer started with "I can provide some general information..." — less confident tone)

Buzzing: alpha=80.0, bravo=73.0
Fractions: 0.523 vs 0.477
```

**Actual worker processing times (from worker terminal logs):**
```
worker_alpha: 4.6s, 5.0s, 4.3s (3 real calibration tasks)
worker_bravo: 5.1s, 4.6s, 3.7s (3 real calibration tasks)
```

**Assessment:** Fractions are 0.523 vs 0.477 — very close to the ideal 0.50/0.50 for identical workers. The small remaining difference (quality 8.0 vs 7.3) is inherent LLM non-determinism that cannot be eliminated, only smoothed by averaging. 3 rounds smooths it enough for practical use.

**Progression across all rounds:**
```
Round 1 (bugs 1+2):     0.909 / 0.091  ← terrible
Round 2 (bug 3 unfixed): 0.333 / 0.667
Round 3 (warmup fail):   0.277 / 0.723  ← worse
Round 4 (two-round):     0.429 / 0.571
Round 5 (cache reset):   0.250 / 0.750  ← quality noise
Round 6 (verbose):       0.571 / 0.429
Round 7 (cleaned prompts): 0.333 / 0.667 ← polling noise
Round 8 (thorough):      0.523 / 0.477  ← GOOD ENOUGH
```

**All 5 bugs are now fixed. Calibration is ready for the real Phase 2 LAN test.**
