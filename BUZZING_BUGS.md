# Buzzing Calibration Bugs — Found During Phase 2 LAN Test (2026-04-11)

> **Found by:** Nir during Phase 2 LAN test on Desktop
> **Must fix before:** Rerunning Phase 2 LAN test
> **Files to fix:** `dwarf_queen_client.py` and `raja_bee.py` — both have `_run_calibration()` with the same bugs

**Status:** Bug 1 (simultaneous) — FIXED. Bug 2 (formula) — FIXED. Bug 3 (order bias) — **NOT FIXED, warmup attempt failed, need two-round reversed-order calibration**.

---

## Bug 1: Simultaneous Calibration Causes False Speed Differences

### What happened

During Buzzing calibration, the DwarfQueen sent the calibration task to BOTH workers **at the same time**. Both workers are on the **same machine** (Desktop), hitting the **same local Ollama instance**. Ollama processes requests **sequentially** (one at a time). 

Result:
- worker_alpha finished in **5.0s** (got Ollama immediately)
- worker_bravo finished in **10.1s** (waited ~5s in Ollama's queue, then processed for ~5s)

The 2x time difference is a **scheduling artifact**, NOT a real performance difference. They are identical workers on identical hardware with the identical model.

### The fix

Calibration tasks must be sent **SEQUENTIALLY**, not simultaneously. The flow should be:

1. Send calibration to worker_alpha
2. **Wait for worker_alpha to complete**
3. Send calibration to worker_bravo
4. **Wait for worker_bravo to complete**

This way each worker gets exclusive Ollama access and the timing reflects **actual processing speed**, not queue position.

### Where in the code

In `_run_calibration()`, the current code posts calibration tasks to ALL subordinates in a loop without waiting:

```python
for sub in self.subordinates:
    # Posts calibration task immediately — all hit Ollama at once
    cal_data = self.kb._request("POST", f"/api/member/{sub_id}/calibration", ...)
    calibration_tasks[sub_id] = {"component_id": comp_id, "start_time": time.time()}
```

Then it waits for all results in a separate polling loop. This means all subordinates are processing concurrently, competing for the same Ollama.

**Fix:** Send calibration to one subordinate, poll until it completes, record time. Then send to the next. Each subordinate gets a fair, uncontested measurement.

---

## Bug 2: Speed Scoring Formula Is Broken

### What happened

The speed scoring formula uses linear interpolation where the fastest always gets 10 and the slowest always gets 1, **regardless of the actual time ratio**:

```python
speed_score = 10.0 - 9.0 * ((elapsed - fastest) / (slowest - fastest))
```

With only 2 workers:
- Fastest → 10.0 (always)
- Slowest → 1.0 (always)

This means:
- If one takes 5.0s and the other takes 5.1s → scores are 10 and 1 (absurd!)
- If one takes 5.0s and the other takes 10.0s → scores are 10 and 1 (a 2x difference becomes 10x)
- If one takes 5.0s and the other takes 50.0s → scores are 10 and 1 (a 10x difference is also 10x)

The formula **destroys all information about the actual ratio** between speeds.

In our test: worker_alpha (5.0s) got buzzing 60.0, worker_bravo (10.1s) got buzzing 6.0. Fractions: 0.909 vs 0.091. That means worker_alpha gets **10x more work** than worker_bravo, even though it's only **2x faster**. The fractions should have been roughly 0.667 vs 0.333.

### The fix

Speed score should be **proportional to actual times**:

```python
speed_score = 10.0 * (fastest / elapsed)
```

Examples with this formula:
- Same speed as fastest → `10 * (5/5)` = **10.0**
- 2x slower than fastest → `10 * (5/10)` = **5.0**
- 3x slower → `10 * (5/15)` = **3.33**
- 10x slower → `10 * (5/50)` = **1.0**

This preserves the actual performance ratio. Two workers that are 2x apart in speed will get buzzings that are 2x apart (assuming same quality), leading to fractions that are 2:1 — which is correct.

### Where in the code

In `_run_calibration()`, the scoring section:

```python
# Current (broken):
if slowest == fastest:
    speed_score = 10.0
else:
    speed_score = 10.0 - 9.0 * ((elapsed - fastest) / (slowest - fastest))

# Should be:
speed_score = 10.0 * (fastest / elapsed)
```

The `min(10.0, max(1.0, ...))` clamping can stay as a safety net.

---

## Both bugs exist in both files

1. **GiantHoneyBee/dwarf_queen_client.py** — `_run_calibration()` method (lines ~196-338)
2. **GiantHoneyBee/raja_bee.py** — `_run_calibration()` method (lines ~209-363)

Both files have identical calibration logic and need the same two fixes.

---

---

## Bug 3: Sequential Calibration Order Bias — Second Worker Always Faster

**Status: NOT FIXED — warmup attempt FAILED**

### What happened (Round 2 — after Bugs 1+2 fixed)

```
worker_alpha: 10.1s  (tested FIRST)  → speed=5.0, quality=6.0, buzzing=30.0
worker_bravo:  5.1s  (tested SECOND) → speed=10.0, quality=6.0, buzzing=60.0
Fractions: 0.333 vs 0.667
```

### What happened (Round 3 — after warmup fix added)

```
Warmup round completed (both workers warmed up)
worker_alpha: 10.1s  (tested FIRST)  → speed=5.1, quality=6.0, buzzing=30.6
worker_bravo:  5.1s  (tested SECOND) → speed=10.0, quality=8.0, buzzing=80.0
Fractions: 0.277 vs 0.723
```

**The warmup did NOT help.** Times are identical to before warmup (10.1s vs 5.1s). The problem is NOT cold model loading. Something else is causing the second worker to consistently take half the time.

### Root cause analysis

The issue is NOT model loading (warmup proved this). Possible real causes:

1. **Ollama KV cache / prompt cache:** Ollama may cache internal computations (KV cache) from the first request. The second request with a similar prompt structure benefits from this cache, even though it's a different worker process. Both workers hit the SAME Ollama instance on localhost.

2. **OS/GPU memory state:** After the first inference, GPU memory is laid out optimally. The second inference benefits from warm GPU caches (L2 cache, memory pages already mapped).

3. **Ollama internal batching or scheduling:** Ollama may have internal optimizations that favor subsequent requests.

### The real fix — test order must not affect scores

Since both workers share the same Ollama, order will ALWAYS matter. Simple warmup cannot fix this. The fix must **cancel out the order effect**:

**Two-round calibration with reversed order:**

1. Round 1: Test worker_alpha FIRST, then worker_bravo. Record times.
2. Round 2: Test worker_bravo FIRST, then worker_alpha. Record times.
3. Average each worker's times across both rounds.

This way each worker is tested once as "first" (disadvantaged) and once as "second" (advantaged). The average cancels out the position effect.

Expected result for identical workers:
- worker_alpha: avg of ~10s (round 1, first) + ~5s (round 2, second) = ~7.5s
- worker_bravo: avg of ~5s (round 1, second) + ~10s (round 2, first) = ~7.5s
- Fractions: ~0.50 vs 0.50

For actually different workers (e.g., one has a better GPU), the real speed difference would still show through in the average.

### Where in the code

In `_run_calibration()` in both files. Replace the single sequential calibration loop with:

```python
# Round 1: test in order A, B, C...
round1_times = {}
for sub in self.subordinates:
    # send calibration, wait, record time
    round1_times[sub_id] = elapsed

# Round 2: test in REVERSE order C, B, A...
round2_times = {}
for sub in reversed(self.subordinates):
    # send NEW calibration question, wait, record time
    round2_times[sub_id] = elapsed

# Average times
for sub_id in round1_times:
    avg_time = (round1_times[sub_id] + round2_times[sub_id]) / 2
```

Note: Round 2 should use a NEW calibration question (generated fresh) to avoid any prompt-level caching.

### Files to fix

1. **GiantHoneyBee/dwarf_queen_client.py** — `_run_calibration()` method
2. **GiantHoneyBee/raja_bee.py** — `_run_calibration()` method

---

## After fixing Bug 3

1. Push fixes to GitHub
2. Desktop does `git pull` in GiantHoneyBee
3. Kill all 3 Desktop bees (Ctrl+C in each terminal)
4. Laptop re-seeds KillerBee database (fresh start)
5. Restart all bees and rerun Phase 2 LAN test
6. Verify identical workers get approximately equal fractions (~0.50 vs 0.50)
