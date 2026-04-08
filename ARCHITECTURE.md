# GiantHoneyBee Architecture Plan

> Written: 2026-04-08 by Claude Opus 4.6 on Laptop Windows
> This is the detailed architecture. Must be reviewed and approved before coding begins.

---

## The Beautiful Insight

The existing Queen Bee has a method called `process_nectar(task) → result`. You give her a task (nectar), she splits it, distributes to workers, combines results, and gives you back an answer (honey).

The RajaBee does the EXACT SAME THING — but her "workers" are Queens, not Worker Bees. From the RajaBee's perspective, each Queen is just a black box that accepts a task and returns a result. She doesn't know (or care) that inside each Queen, there's a whole hive of workers doing the actual processing.

This means: **the RajaBee is just a Queen whose workers happen to be other Queens.**

And THIS is what makes it N-level: a Queen's "worker" could be another RajaBee (who has Queens under her, who have Workers under them). It's recursive. Turtles all the way down.

---

## Phase 1 Architecture: Localhost Test

### What we need to build:

**1. A simple HTTP wrapper around the existing Queen Bee**

The existing Queen has `process_nectar(task) → result`. We wrap this in a tiny HTTP server:

```
POST http://localhost:5000/process
Body: {"task": "Summarize the history of Rome"}
Response: {"result": "Rome was founded in 753 BC..."}
```

This is a THIN wrapper. Maybe 20 lines of code. It just accepts a task over HTTP, calls `process_nectar()`, and returns the result. The Queen code stays COMPLETELY UNTOUCHED.

**2. The RajaBee class**

```python
class RajaBee:
    def __init__(self, model_name, queen_endpoints):
        self.model_name = model_name      # AI model for splitting/combining
        self.queen_endpoints = queen_endpoints  # ["http://localhost:5000", "http://localhost:5001", ...]
        self.ai = OllamaClient()
    
    def process_royal_nectar(self, task):
        # Step 1: Split task into N major pieces (one per Queen)
        pieces = self.split_task(task, len(self.queen_endpoints))
        
        # Step 2: Send each piece to a different Queen IN PARALLEL
        queen_results = self.delegate_to_queens(pieces)
        
        # Step 3: Combine all Queens' results into one mega-answer
        royal_honey = self.combine_results(task, queen_results)
        
        return royal_honey
```

**3. The splitting prompt (different from Queen's)**

The Queen splits into small subtasks ("write paragraph 1", "write paragraph 2").
The RajaBee splits into MAJOR COMPONENTS ("research the political history", "research the military history", "research the cultural history"). Each component is big enough that a Queen + her workers need to handle it.

**4. The delegation (parallel HTTP calls)**

```python
def delegate_to_queens(self, pieces):
    results = []
    with ThreadPoolExecutor(max_workers=len(self.queen_endpoints)) as executor:
        futures = {}
        for i, piece in enumerate(pieces):
            endpoint = self.queen_endpoints[i]
            future = executor.submit(self.send_to_queen, endpoint, piece)
            futures[future] = endpoint
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
    
    return results
```

**5. The combining prompt (different from Queen's)**

The Queen combines subtask results into one answer.
The RajaBee combines QUEEN-LEVEL results into a MEGA answer. The prompt should be aware that each input is already a synthesized, complete section — not a raw subtask result.

---

## File Structure for Phase 1

```
GiantHoneyBee/
├── README.md                  (already created)
├── ARCHITECTURE.md            (this file)
├── raja_bee.py                (the RajaBee class)
├── queen_http_wrapper.py      (thin HTTP wrapper around existing Queen)
├── demo_raja.py               (Phase 1 demo: everything on localhost)
└── requirements.txt           (flask/fastapi, requests)
```

---

## How Phase 1 Demo Works (localhost, one machine)

### Setup:
1. Start Ollama with a small model (e.g., qwen2.5:1.5b)
2. Terminal 1: `python queen_http_wrapper.py --port 5000 --model qwen2.5:1.5b --workers 1`
   - Starts a Queen on port 5000 with 1 local worker
3. Terminal 2: `python queen_http_wrapper.py --port 5001 --model qwen2.5:1.5b --workers 1`
   - Starts a Queen on port 5001 with 1 local worker
4. Terminal 3: `python demo_raja.py --model llama3.2:3b --queens http://localhost:5000,http://localhost:5001`
   - Starts the RajaBee, connected to both Queens

### What happens:
1. User types a complex task
2. RajaBee splits it into 2 major pieces (one per Queen)
3. RajaBee sends piece 1 to Queen on port 5000
4. RajaBee sends piece 2 to Queen on port 5001 (IN PARALLEL)
5. Each Queen splits her piece into subtasks for her worker(s)
6. Each Queen's worker(s) process subtasks
7. Each Queen combines her worker results into one answer
8. Each Queen sends her answer back to the RajaBee
9. RajaBee combines both Queens' answers into the MEGA answer
10. User sees the final result

### What this proves:
- Two-level hierarchy WORKS
- Parallel execution across Queens
- Queens don't know they're being orchestrated
- The existing HoneycombOfAI code is UNTOUCHED

---

## Making it N-Level (design principle, not Phase 1)

The key insight: the `queen_http_wrapper.py` exposes ANY process_nectar-compatible object as an HTTP endpoint. If we make RajaBee ALSO have a `process_nectar()` method, then a RajaBee can be wrapped in the same HTTP wrapper, and ANOTHER RajaBee can call it.

```
RajaBee Level 3
  └── calls RajaBee Level 2 (via HTTP wrapper)
       └── calls Queen Level 1 (via HTTP wrapper)
            └── calls Workers (local)
```

Each level is the same pattern: receive task → split → delegate → combine. The only difference is who you delegate to.

---

## What We Do NOT Change

- queen_bee.py — UNTOUCHED
- worker_bee.py — UNTOUCHED
- All existing HoneycombOfAI files — UNTOUCHED
- BeehiveOfAI — UNTOUCHED

We only ADD new files in the GiantHoneyBee repo.

---

## Dependencies

- The GiantHoneyBee repo needs to IMPORT from HoneycombOfAI (specifically QueenBee, WorkerBee, OllamaClient)
- Options:
  a. Add HoneycombOfAI to Python path
  b. Symlink
  c. pip install from local path
  d. Just copy the needed files (simplest for Phase 1)

Recommended for Phase 1: option (a) — add HoneycombOfAI to path. Clean, no copying, no package management.

---

## Estimated Effort

- queen_http_wrapper.py: ~50 lines
- raja_bee.py: ~150 lines
- demo_raja.py: ~30 lines
- Total: ~230 lines of new code

This is a one-session job for Sonnet 4.6.
