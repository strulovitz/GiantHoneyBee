# Buzzing — The BeehiveOfAI Performance Rating System

> "Buzzing" is the sound that bees make. In our system, it's how we measure
> how much work each bee can handle, and how to divide work fairly.

---

## The Problem

In a distributed AI system, different machines have different capabilities.
Some have powerful GPUs, some have weak CPUs. Some run smart 14B models,
some run tiny 1.5B models. We need to know how to divide work proportionally.

But we can't trust self-reported specs. The software is open source — anyone
can modify it to report fake capabilities. We need a system where:

1. Nobody can cheat
2. Only relative performance matters (not absolute scores)
3. The same scale works at every level of the hierarchy
4. LLMs don't need to do math — they just see simple fractions

---

## Core Concept: The Boss Tests The Employee

Every boss tests the level directly below them:

```
RajaBee tests his GiantQueens
GiantQueen tests her DwarfQueens
DwarfQueen tests her Workers
```

**Why this works — incentive alignment:**

- **Workers can't inflate their own scores** — their boss measures them, not themselves.
- **Bosses won't inflate their subordinates** — if they do, they get assigned work their team can't handle, and they look bad to THEIR boss.
- **Bosses won't deflate their subordinates** — less work assigned means less pay.
- **Every level is honest because their own success depends on accurate scores below them.**

**Why the boss CAN judge:**

In our system, the boss is ALWAYS smarter than their subordinates. The RajaBee
runs a bigger/better LLM than GiantQueens. GiantQueens run better LLMs than
DwarfQueens. DwarfQueens run better LLMs than Workers. So every boss can
genuinely evaluate the quality of work below them.

---

## The Buzzing Score

Each Worker's Buzzing is calculated by their boss (DwarfQueen):

```
Worker Buzzing = buzzing_speed (1-10) × buzzing_quality (1-10) = 1 to 100
```

**If either dimension is zero, the total is zero:**
- Perfect quality but takes forever? Useless — we never get the result.
- Instant response but garbage quality? Useless — the answer is worthless.

That's why it's multiplication, not addition.

### How Speed Is Measured (objective)

1. Boss posts the SAME calibration task to all subordinates simultaneously
2. Boss records how long each one takes
3. Fastest in the group → speed score 10
4. Slowest in the group → speed score 1
5. Others interpolated linearly between 1 and 10

### How Quality Is Measured (by the boss's LLM)

1. Boss collects all subordinates' answers to the same calibration task
2. Boss uses its own (smarter) LLM to rate each answer from 1 to 10
3. Since the same LLM judges all answers, the grading is consistent within the group

---

## The Calibration Test

**Who creates the test?** The boss creates it using their own LLM. Every test is:
- **Generated on the fly** — never seen before, can't be anticipated
- **Unique to this group** — not in any config file or GitHub repo
- **The same for all subordinates** — everyone in the group gets the identical test

**Why not use a standard test bank?**
- Open source = anyone can read the test bank and pre-compute answers
- Dynamic tests from a smarter LLM are impossible to game

**Why hard/easy exams don't matter:**
- We only care about RELATIVE performance within the group
- If the exam is hard, everyone struggles — but the ratios are similar
- If the exam is easy, everyone does well — but the ratios are similar
- Fractions always sum to 1 regardless of difficulty

---

## From Buzzing to Fractions

### Step 1: Worker Buzzing (the foundation)

Each Worker gets a buzzing score (1-100) from their DwarfQueen boss.

### Step 2: Capacity (internal calculation, never shown to LLMs)

```
Worker capacity      = its buzzing (e.g., 80)
DwarfQueen capacity  = sum of her workers' buzzings (e.g., 80 + 70 + 60 = 210)
GiantQueen capacity  = sum of her DwarfQueens' capacities (e.g., 210 + 175 = 385)
```

### Step 3: Fractions (what the LLM actually sees)

At every level, each subordinate gets a decimal fraction. All fractions sum to 1.

```
subordinate_fraction = subordinate_capacity / total_capacity_of_all_subordinates
```

### Full Example

```
RajaBee
├── GiantQueen A
│   ├── DwarfQueen A1
│   │   ├── Worker (buzzing: 80)
│   │   ├── Worker (buzzing: 70)
│   │   └── Worker (buzzing: 60)
│   └── DwarfQueen A2
│       ├── Worker (buzzing: 90)
│       └── Worker (buzzing: 85)
└── GiantQueen B
    └── DwarfQueen B1
        └── Worker (buzzing: 95)
```

**Capacities bubble up:**

```
DwarfQueen A1 capacity = 80 + 70 + 60 = 210
DwarfQueen A2 capacity = 90 + 85     = 175
DwarfQueen B1 capacity = 95

GiantQueen A capacity  = 210 + 175    = 385
GiantQueen B capacity  = 95

Total                  = 385 + 95     = 480
```

**RajaBee sees fractions:**

```
GiantQueen A: 385/480 = 0.802
GiantQueen B:  95/480 = 0.198
                        ─────
                 Sum  = 1.000
```

RajaBee tells its LLM: *"Split this task into 2 parts. Part 1 should be about
80% of the total work. Part 2 should be about 20%."*

**GiantQueen A sees fractions for her DwarfQueens:**

```
DwarfQueen A1: 210/385 = 0.545
DwarfQueen A2: 175/385 = 0.455
                         ─────
                  Sum  = 1.000
```

**DwarfQueen A1 sees fractions for her Workers:**

```
Worker 1: 80/210 = 0.381
Worker 2: 70/210 = 0.333
Worker 3: 60/210 = 0.286
                   ─────
            Sum  = 1.000
```

---

## Why Fractions (Not Raw Numbers)

LLMs are bad at math. We don't want to tell the RajaBee:

> "GiantQueen A has capacity 2,250 and GiantQueen B has capacity 810.
> Calculate the proportional split."

Instead we say:

> "Split this task. Part 1 should cover about 0.74 of the work.
> Part 2 should cover about 0.26 of the work."

The LLM just needs to understand "make one part bigger than the other."
People naturally say "half and half" or "a third of the work."
Fractions that sum to 1 are the most intuitive representation.

---

## The Calibration Flow

```
1. Boss's LLM generates a test question
2. Boss posts it to KillerBee as a calibration task
3. ALL subordinates receive the SAME test
4. Subordinates process and post results to KillerBee
5. Boss collects all results
6. Boss measures speed (objective: wall clock timing)
7. Boss's LLM judges quality of each answer (1-10)
8. Boss calculates each subordinate's buzzing (speed × quality)
9. Boss calculates fractions (buzzing / total)
10. Boss reports fractions to KillerBee
11. KillerBee stores them and makes them available to higher levels
```

Same process at every level of the hierarchy.

---

## Where Calculations Happen

| What | Where | Why |
|------|-------|-----|
| Generating the calibration test | Boss bee (client) | Only the boss's LLM can create a good test |
| Timing the subordinates | Boss bee (client) | Boss measures wall clock time |
| Judging quality | Boss bee (client) | Boss's smarter LLM evaluates answers |
| Calculating buzzing & fractions | Boss bee (client) | Boss has the data and the incentive for accuracy |
| Storing fractions | KillerBee (website) | Central storage, available to all levels |
| Providing fractions to higher levels | KillerBee (website) | Aggregation and API responses |

---

## Key Design Principles

1. **Nobody tests themselves.** Your boss tests you.
2. **The boss is always smarter.** Guaranteed by the model hierarchy.
3. **Same test for the whole group.** Fair comparison.
4. **Only relative performance matters.** Fractions sum to 1.
5. **Tests are generated dynamically.** Can't be gamed from source code.
6. **Multiplication, not addition.** Zero speed or zero quality = zero buzzing.
7. **Fractions, not raw numbers.** LLMs understand "0.80 of the work" better than "capacity 2,250."
8. **Incentive alignment at every level.** Honest reporting = better results = more work = more pay.
