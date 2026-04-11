"""
RajaBee — The King of the Bees (KillerBee API Client)
======================================================
Named after Megachile pluto (Wallace's Giant Bee), the largest bee in the world.

The RajaBee is the TOP of the hierarchy. It communicates ONLY through the
KillerBee website API. No direct HTTP to Queens or Workers.

Workflow:
1. Login to KillerBee
2. Poll for pending jobs in the swarm
3. When a job arrives: use local Ollama to split into components
4. Post components to KillerBee (job split API)
5. Poll KillerBee until all components have results
6. Use local Ollama to combine results
7. Post final result to KillerBee

Hierarchy: RajaBee -> GiantQueens -> DwarfQueens -> Workers
All communication goes through KillerBee. No direct HTTP between bees.
"""

import sys
import os
import time
import json
import argparse

# Add HoneycombOfAI to path for AI backend
HONEYCOMB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'HoneycombOfAI')
sys.path.insert(0, HONEYCOMB_PATH)

from ollama_client import OllamaClient
from killerbee_client import KillerBeeClient


def print_banner(text: str, char: str = "="):
    line = char * 60
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}")


class RajaBee:
    """
    The Raja Bee -- King of the Bees.

    Connects to KillerBee website, polls for jobs, splits them into
    components for GiantQueens, waits for results, combines them.
    """

    def __init__(self, server_url: str, swarm_id: int,
                 username: str, password: str,
                 model_name: str = "llama3.2:3b",
                 ollama_url: str = "http://localhost:11434",
                 poll_interval: int = 5):
        self.server_url = server_url
        self.swarm_id = swarm_id
        self.model_name = model_name
        self.poll_interval = poll_interval
        self.subordinate_type = "giant_queen"
        self.rediscovery_interval = 10  # re-check for new subordinates every N poll cycles
        self._poll_count = 0
        self.member_id = None

        # Buzzing system: subordinates and their fractions
        self.subordinates = []   # list of subordinate dicts from KillerBee
        self.fractions = []      # list of {member_id, name, fraction} dicts
        self._last_known_capacities = {}  # member_id -> capacity (for change detection)

        # KillerBee API client (all communication goes through here)
        self.kb = KillerBeeClient(server_url, username, password)

        # Local Ollama for AI processing (splitting and combining)
        self.ai = OllamaClient(base_url=ollama_url)

    def start(self):
        """Login, register, and start the main loop."""
        print_banner("RajaBee -- King of the Bees")
        print(f"  Server:    {self.server_url}")
        print(f"  Swarm:     {self.swarm_id}")
        print(f"  Model:     {self.model_name}")
        print(f"  Username:  {self.kb.username}")

        # Check Ollama
        if not self.ai.is_available():
            print("\n  [ERROR] Cannot connect to Ollama! Is it running?")
            return False
        print(f"  Ollama:    Connected ({self.ai.backend_name()})")

        # Login to KillerBee
        try:
            login_data = self.kb.login()
            print(f"  KillerBee: Logged in (user_id={self.kb.user_id})")
        except Exception as e:
            print(f"\n  [ERROR] Cannot login to KillerBee: {e}")
            return False

        # Register as a RajaBee member so we get a proper member_id
        try:
            reg_data = self.kb.register_member(
                self.swarm_id, "raja", self.model_name
            )
            self.member_id = reg_data.get("member_id", self.kb.user_id)
            print(f"  Registered as RajaBee (member_id={self.member_id})")
        except Exception as e:
            print(f"  [WARN] Registration: {e}")
            self.member_id = self.kb.user_id

        # ── Buzzing: Discover, Calibrate, Get Fractions ──────────────
        # Look for GiantQueens first; if none, look for DwarfQueens directly
        self._buzzing_cycle("giant_queen")
        if not self.subordinates:
            print("  [BUZZING] No GiantQueens found. Looking for DwarfQueens directly...")
            self.subordinate_type = "dwarf_queen"
            self._buzzing_cycle("dwarf_queen")
        # ─────────────────────────────────────────────────────────────

        print_banner("RajaBee is RUNNING. Polling for jobs...")
        self._main_loop()
        return True

    # ── Buzzing: Discovery, Calibration, Fractions ─────────────────

    def _buzzing_cycle(self, subordinate_type: str):
        """Run full Buzzing cycle: discover, calibrate, get fractions."""
        print_banner("BUZZING: Discovering & Calibrating Subordinates")
        old_count = len(self.subordinates)
        self._discover_and_claim_subordinates(subordinate_type)
        if self.subordinates:
            needs_recalibration = False

            # Check 1: new subordinates joined
            if len(self.subordinates) > old_count or not self.fractions:
                needs_recalibration = True
                print("  [BUZZING] New subordinates or first calibration.")

            # Check 2: any subordinate's capacity changed (they gained/lost workers)
            if not needs_recalibration:
                try:
                    current_fractions = self.kb.get_fractions(self.member_id)
                    for sub in current_fractions.get("subordinates", []):
                        sub_id = sub.get("member_id")
                        sub_cap = sub.get("capacity") or 0
                        old_cap = self._last_known_capacities.get(sub_id, sub_cap)
                        if abs(sub_cap - old_cap) > 0.01:
                            print(f"  [BUZZING] {sub.get('username', sub_id)}'s "
                                  f"capacity changed: {old_cap:.1f} -> {sub_cap:.1f}")
                            needs_recalibration = True
                            break
                except Exception:
                    pass  # If we can't check, skip

            if needs_recalibration:
                self._run_calibration()
                self._fetch_fractions()
                # Store current capacities for future comparison
                try:
                    current = self.kb.get_fractions(self.member_id)
                    for sub in current.get("subordinates", []):
                        self._last_known_capacities[sub.get("member_id")] = sub.get("capacity") or 0
                except Exception:
                    pass
            else:
                print("  [BUZZING] No changes. Fractions unchanged.")
        else:
            print("  [BUZZING] No subordinates found yet. "
                  "Will check again periodically.")

    def _discover_and_claim_subordinates(self, subordinate_type: str):
        """Find unassigned members and claim them. Also load existing."""
        # Check existing subordinates first
        try:
            existing = self.kb.get_subordinates(self.member_id)
            if existing:
                print(f"  [BUZZING] Found {len(existing)} existing "
                      f"subordinate(s)")
                for sub in existing:
                    sub_id = sub.get("member_id") or sub.get("id")
                    sub_name = sub.get("username", f"member-{sub_id}")
                    print(f"    - {sub_name} (member_id={sub_id})")
                self.subordinates = existing
        except Exception as e:
            print(f"  [BUZZING] Could not fetch existing subordinates: {e}")

        # Look for unassigned members to claim
        try:
            unassigned = self.kb.get_unassigned_members(
                self.swarm_id, subordinate_type
            )
            if unassigned:
                print(f"  [BUZZING] Found {len(unassigned)} unassigned "
                      f"{subordinate_type}(s) to claim")
                for member in unassigned:
                    m_id = member.get("member_id") or member.get("id")
                    m_name = member.get("username", f"member-{m_id}")
                    try:
                        self.kb.claim_subordinate(self.member_id, m_id)
                        print(f"    - Claimed {m_name} (member_id={m_id})")
                        self.subordinates.append(member)
                    except Exception as e:
                        print(f"    - Failed to claim {m_name}: {e}")
            else:
                print(f"  [BUZZING] No unassigned {subordinate_type}s found")
        except Exception as e:
            print(f"  [BUZZING] Could not fetch unassigned members: {e}")

        print(f"  [BUZZING] Total subordinates: {len(self.subordinates)}")

    def _run_calibration(self):
        """Generate a test, send to all subordinates, score them."""
        print_banner("BUZZING: Running Calibration Test", char="-")

        # Step 1: Generate calibration question using own LLM
        print("  [BUZZING] Generating calibration test question...")
        test_question = self.ai.ask(
            prompt=("Generate a short test question that requires a detailed "
                    "2-paragraph answer about any topic. Just output the "
                    "question, nothing else."),
            model=self.model_name,
            temperature=0.7
        ).strip()
        print(f"  [BUZZING] FULL CALIBRATION QUESTION:")
        print(f"  ---BEGIN---")
        print(f"  {test_question}")
        print(f"  ---END---")

        # Sequential calibration — one subordinate at a time, with a dummy
        # reset question before each real measurement. The dummy overwrites
        # the LLM backend's prompt cache so the real question gets a full,
        # fair evaluation. Without this, the second worker tested is ~2-3x
        # faster due to cached prompt tokens. See BUZZING_BUGS.md.
        dummy_question = "Name three colors of the rainbow. Reply in three words only."
        results = {}
        for sub in self.subordinates:
            sub_id = sub.get("member_id") or sub.get("id")
            sub_name = sub.get("username", f"member-{sub_id}")
            try:
                # Dummy reset: flush LLM prompt cache with unrelated question
                print(f"  [BUZZING] Resetting cache for {sub_name}...")
                try:
                    dummy_data = self.kb._request(
                        "POST", f"/api/member/{sub_id}/calibration", {
                            "task": dummy_question,
                            "component_type": "calibration"
                        }
                    )
                    dummy_comp_id = dummy_data.get("component_id") or dummy_data.get("id")
                    dummy_waited = 0
                    while dummy_waited < 120:
                        time.sleep(self.poll_interval)
                        dummy_waited += self.poll_interval
                        try:
                            dummy_resp = self.kb._request(
                                "GET", f"/api/component/{dummy_comp_id}/status"
                            )
                            if dummy_resp.get("status") == "completed":
                                print(f"  [BUZZING] Cache reset for {sub_name}")
                                break
                        except:
                            pass
                except Exception as e:
                    print(f"  [BUZZING] Cache reset failed for {sub_name}: {e}")

                # Real calibration measurement
                print(f"  [BUZZING] Sending calibration to {sub_name}...")
                start_time = time.time()
                cal_data = self.kb._request(
                    "POST", f"/api/member/{sub_id}/calibration", {
                        "task": test_question,
                        "component_type": "calibration"
                    }
                )
                comp_id = cal_data.get("component_id") or cal_data.get("id")
                max_wait = 600
                waited = 0
                while waited < max_wait:
                    time.sleep(self.poll_interval)
                    waited += self.poll_interval
                    try:
                        comp_resp = self.kb._request(
                            "GET", f"/api/component/{comp_id}/status"
                        )
                        if (comp_resp.get("status") == "completed"
                                and comp_resp.get("result")):
                            elapsed = time.time() - start_time
                            results[sub_id] = {
                                "result": comp_resp["result"],
                                "elapsed_time": elapsed,
                                "name": sub_name
                            }
                            print(f"  [BUZZING] {sub_name} completed "
                                  f"in {elapsed:.1f}s")
                            print(f"  [BUZZING] {sub_name} FULL ANSWER:")
                            print(f"  ---BEGIN---")
                            print(f"  {comp_resp['result']}")
                            print(f"  ---END---")
                            break
                    except:
                        pass
                    print(f"  [BUZZING] Waiting for {sub_name}... "
                          f"({waited}s)", end="\r")
                else:
                    print(f"  [BUZZING] {sub_name} timed out after "
                          f"{max_wait}s")
            except Exception as e:
                print(f"  [BUZZING] Failed to send calibration to "
                      f"{sub_name}: {e}")

        if not results:
            print("  [BUZZING] No calibration results received. Skipping.")
            return

        # Score each subordinate
        print_banner("BUZZING: Scoring Subordinates", char="-")

        times = {sid: r["elapsed_time"] for sid, r in results.items()}
        fastest = min(times.values())

        for sub_id, r in results.items():
            elapsed = r["elapsed_time"]
            # Proportional speed: fastest gets 10, 2x slower gets 5, etc.
            speed_score = 10.0 * (fastest / elapsed)
            speed_score = round(max(1.0, min(10.0, speed_score)), 1)

            quality_prompt = (
                f"Rate the following answer from 1 to 10 for completeness "
                f"and accuracy. The question was: \"{test_question}\"\n\n"
                f"Answer to rate:\n{r['result']}\n\n"
                f"Reply with ONLY a single number from 1 to 10, nothing else."
            )
            print(f"  [BUZZING] Judging {r['name']}...")
            print(f"  [BUZZING] QUALITY PROMPT SENT TO JUDGE:")
            print(f"  ---BEGIN PROMPT---")
            print(f"  {quality_prompt}")
            print(f"  ---END PROMPT---")
            quality_text = self.ai.ask(
                prompt=quality_prompt,
                model=self.model_name,
                temperature=0.1
            ).strip()
            print(f"  [BUZZING] JUDGE RAW RESPONSE: \"{quality_text}\"")

            # Parse quality score
            try:
                quality_score = float(
                    ''.join(c for c in quality_text if c.isdigit() or c == '.')
                )
                quality_score = max(1.0, min(10.0, quality_score))
            except (ValueError, TypeError):
                quality_score = 5.0  # Default if parsing fails

            quality_score = round(quality_score, 1)
            buzzing = round(speed_score * quality_score, 1)

            print(f"  [BUZZING] {r['name']}: speed={speed_score}, "
                  f"quality={quality_score}, buzzing={buzzing}")

            # Report to KillerBee
            try:
                self.kb.report_buzzing(
                    sub_id, speed_score, quality_score, self.member_id
                )
                print(f"  [BUZZING] Reported buzzing for {r['name']}")
            except Exception as e:
                print(f"  [BUZZING] Failed to report buzzing for "
                      f"{r['name']}: {e}")

        # Step 5: Recalculate capacity and fractions
        try:
            self.kb.recalculate_member(self.member_id)
            print("  [BUZZING] Recalculated capacity and fractions")
        except Exception as e:
            print(f"  [BUZZING] Recalculate failed: {e}")

    def _fetch_fractions(self):
        """Fetch fractions from KillerBee and store locally."""
        try:
            fractions_data = self.kb.get_fractions(self.member_id)
            self.fractions = fractions_data.get("subordinates", [])
            if self.fractions:
                print_banner("BUZZING: Fractions for Splitting", char="-")
                for f in self.fractions:
                    name = f.get("username", f.get("name", "unknown"))
                    frac = f.get("fraction") or 0
                    print(f"  {name}: {frac:.3f}")
                print(f"  Total: {sum(f.get('fraction', 0) for f in self.fractions):.3f}")
            else:
                print("  [BUZZING] No fractions received. "
                      "Will use equal splitting.")
        except Exception as e:
            print(f"  [BUZZING] Could not fetch fractions: {e}")

    # ── Main Loop ─────────────────────────────────────────────────────

    def _main_loop(self):
        """Poll KillerBee for pending jobs and process them."""
        while True:
            try:
                # Periodically re-discover subordinates (new bees may have joined)
                self._poll_count += 1
                if self._poll_count % self.rediscovery_interval == 0:
                    self._buzzing_cycle(self.subordinate_type)

                # Don't accept jobs until we have subordinates
                if not self.subordinates:
                    print(f"  Waiting for subordinates to join... "
                          f"(checking every {self.poll_interval}s)", end="\r")
                    # Check for new subordinates every cycle while we have none
                    self._buzzing_cycle(self.subordinate_type)
                    time.sleep(self.poll_interval)
                    continue

                jobs = self.kb.get_pending_jobs(self.swarm_id)
                if jobs:
                    for job in jobs:
                        job_id = job.get("id") or job.get("job_id")
                        task = job.get("task") or job.get("prompt", "")
                        print(f"\n  [JOB {job_id}] Received: {task[:80]}...")
                        self._process_job(job_id, task)
                else:
                    print(f"  Polling... no pending jobs. "
                          f"({len(self.subordinates)} subordinates, "
                          f"waiting {self.poll_interval}s)", end="\r")
            except Exception as e:
                print(f"  [ERROR] Polling failed: {e}")

            time.sleep(self.poll_interval)

    def _process_job(self, job_id: int, task: str):
        """Process a single job: split, wait for results, combine."""
        total_start = time.time()

        # Step 1: Use local Ollama to split the task into components
        print(f"  [JOB {job_id}] Splitting task into components...")
        components = self._split_task(task)
        print(f"  [JOB {job_id}] Split into {len(components)} components")

        for i, comp in enumerate(components):
            print(f"    Component {i+1}: {comp[:70]}...")

        # Step 2: Post components to KillerBee
        component_data = [{"task": c} for c in components]
        try:
            split_result = self.kb.split_job(job_id, component_data)
            print(f"  [JOB {job_id}] Components posted to KillerBee")
        except Exception as e:
            print(f"  [JOB {job_id}] [ERROR] Failed to post components: {e}")
            return

        # Step 3: Poll until all components have results
        print(f"  [JOB {job_id}] Waiting for GiantQueens to process components...")
        component_results = self._wait_for_components(job_id, split_result)

        if not component_results:
            print(f"  [JOB {job_id}] [ERROR] No component results received")
            return

        # Step 4: Combine results using local Ollama
        print(f"  [JOB {job_id}] Combining {len(component_results)} results...")
        final_result = self._combine_results(task, component_results)

        total_time = time.time() - total_start

        # Step 5: Post final result to KillerBee
        try:
            self.kb.post_job_result(job_id, final_result, total_time)
            print(f"  [JOB {job_id}] COMPLETE! Royal Honey delivered "
                  f"in {total_time:.1f}s")
        except Exception as e:
            print(f"  [JOB {job_id}] [ERROR] Failed to post result: {e}")

    def _split_task(self, task: str) -> list:
        """Use local Ollama to split a task into major components.

        If fractions are available from Buzzing calibration, the number of
        components matches the number of subordinates, and each component
        is sized proportionally by fraction.
        """
        num_components = len(self.fractions) if self.fractions else None

        if num_components and num_components >= 2:
            # Build fraction instructions for the prompt
            fraction_lines = []
            for i, f in enumerate(self.fractions):
                name = f.get("username", f.get("name", f"Subordinate {i+1}"))
                frac = f.get("fraction", round(1.0 / num_components, 2))
                fraction_lines.append(
                    f"Component {i+1} should cover about {frac:.2f} "
                    f"of the total work (for {name})"
                )
            fraction_instructions = "\n".join(fraction_lines)

            prompt = f"""Split this into exactly {num_components} independent components.
Each covers a different part. Together they fully cover the task.

Size proportionally:
{fraction_instructions}

Task: {task}

Return ONLY a JSON array of exactly {num_components} strings."""
        else:
            prompt = f"""Split this into 2-4 independent components.
Each covers a different part. Together they fully cover the task.

Task: {task}

Return ONLY a JSON array of strings."""

        components = self.ai.ask_for_json_list(
            prompt=prompt,
            model=self.model_name,
            temperature=0.3
        )

        if not components or len(components) < 2:
            # Fallback: treat the whole task as one component
            components = [task]

        return components

    def _wait_for_components(self, job_id: int, split_result: dict) -> list:
        """Poll KillerBee until all components for this job have results."""
        # Get component IDs from the split result
        components_info = split_result.get("components", [])
        component_ids = [c["id"] for c in components_info]

        if not component_ids:
            print(f"  [JOB {job_id}] [ERROR] No component IDs from split")
            return []

        print(f"  [JOB {job_id}] Tracking {len(component_ids)} components: {component_ids}")

        max_wait = 3600  # 1 hour max
        waited = 0

        while waited < max_wait:
            time.sleep(self.poll_interval)
            waited += self.poll_interval

            try:
                all_done = True
                results = []

                for comp_id in component_ids:
                    comp_resp = self.kb._request("GET", f"/api/component/{comp_id}/status")
                    if comp_resp.get("status") == "completed" and comp_resp.get("result"):
                        results.append({
                            "task": comp_resp.get("task", ""),
                            "result": comp_resp.get("result"),
                        })
                    else:
                        all_done = False

                if all_done and results:
                    print(f"  [JOB {job_id}] All {len(results)} components "
                          f"completed after {waited}s")
                    return results

                completed = len(results)
                print(f"  [JOB {job_id}] Waiting... "
                      f"{completed}/{len(component_ids)} components done "
                      f"({waited}s elapsed)", end="\r")

            except Exception as e:
                print(f"  [JOB {job_id}] [WARN] Poll error: {e}")

        print(f"  [JOB {job_id}] [TIMEOUT] Waited {max_wait}s")
        return []

    def _combine_results(self, original_task: str,
                         component_results: list) -> str:
        """Use local Ollama to combine component results into Royal Honey."""
        formatted = ""
        for i, cr in enumerate(component_results):
            task_desc = cr.get("task", f"Component {i+1}")
            result_text = cr.get("result", "[No result]")
            formatted += f"\n{'='*40}\n"
            formatted += f"SECTION {i+1}: {task_desc[:60]}\n"
            formatted += f"{'='*40}\n"
            formatted += f"{result_text}\n"

        prompt = f"""Combine these {len(component_results)} results into one answer.

Original question: {original_task}

Results:
{formatted}

Combine into one coherent answer. Remove redundancy, keep all important details."""

        return self.ai.ask(
            prompt=prompt,
            model=self.model_name,
            temperature=0.5
        )


def main():
    parser = argparse.ArgumentParser(
        description="RajaBee -- King of the Bees. "
                    "Connects to KillerBee website API."
    )
    parser.add_argument('--server', type=str, required=True,
                        help='KillerBee server URL (e.g., http://KILLERBEE:8877)')
    parser.add_argument('--swarm-id', type=int, required=True,
                        help='Swarm ID to join')
    parser.add_argument('--username', type=str, required=True,
                        help='Username for KillerBee login')
    parser.add_argument('--password', type=str, required=True,
                        help='Password for KillerBee login')
    parser.add_argument('--model', type=str, default='llama3.2:3b',
                        help='Ollama model name (default: llama3.2:3b)')
    parser.add_argument('--ollama-url', type=str,
                        default='http://localhost:11434',
                        help='Ollama API URL (default: http://localhost:11434)')
    parser.add_argument('--poll-interval', type=int, default=5,
                        help='Seconds between polls (default: 5)')
    args = parser.parse_args()

    raja = RajaBee(
        server_url=args.server,
        swarm_id=args.swarm_id,
        username=args.username,
        password=args.password,
        model_name=args.model,
        ollama_url=args.ollama_url,
        poll_interval=args.poll_interval
    )

    raja.start()


if __name__ == '__main__':
    main()
