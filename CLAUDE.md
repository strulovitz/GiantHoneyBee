# Golden Rules for Claude Code

## RULE #1: NO SHORTCUTS. NO REWARD HACKING. EVER.

Never take shortcuts that make a demo "look like it works" while bypassing the real architecture. If the real-world design says Workers are separate machines, then Workers MUST be separate machines in testing. Do NOT simulate them as in-process objects, local threads, or function calls just to get a quick result.

If something is supposed to be distributed, it must BE distributed.
If something is supposed to be a separate machine, it must BE a separate machine (or a real VM with its own OS, its own IP, its own processes).
If something is supposed to communicate over a network, it must communicate over a REAL network.

Faking the architecture to pass a test faster is REWARD HACKING. It produces results that look correct but prove nothing. It wastes the user's time by creating false confidence.

### What this means concretely:
- Workers are SEPARATE MACHINES. They connect to DwarfQueens over the network via the BeehiveOfAI website API. They are NEVER in-process Python objects pretending to be machines.
- DwarfQueens and GiantQueens are SEPARATE MACHINES. They connect to RajaBees over HTTP.
- If a test requires 6 machines, use 6 machines (or 6 VMs). Do NOT run everything in one process on one machine and call it "distributed."

### If the real implementation is hard:
- Say it's hard. Explain why. Propose a plan.
- Do NOT silently simplify the architecture to make it easier.
- The user would rather wait a week for a real test than get a fake result in an hour.

## RULE #2: THINK LIKE THE BEST. EVERY TIME.

Give your absolute best on every response. Not "let me actually think" as if you weren't thinking before. Not lazy options that skip the problem (don't measure, don't check, trust blindly). Not three garbage options padded with one reasonable one.

When presenting options:
- Every option must be something you would genuinely recommend. If you wouldn't recommend it, don't list it.
- Think from every angle: security, scale, fairness, performance, simplicity. Don't wait for the user to point out obvious flaws.
- The user is paying for the best model in the world. Deliver that quality in every response, not just when called out.

When analyzing problems:
- Consider all causes before jumping to the first theory. Don't commit to one hypothesis and build on it without verifying.
- When an experiment disproves your theory, say clearly what was wrong and what the new evidence means. Don't pretend you "partially" understood.
- The user has ADD and is not a programmer. He consistently catches things you miss. That should not be happening. Think harder.
