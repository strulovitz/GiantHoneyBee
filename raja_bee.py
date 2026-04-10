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
        self.member_id = None

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

        # RajaBee is the swarm owner — no need to register as a member
        self.member_id = self.kb.user_id
        print(f"  RajaBee ready (user_id={self.member_id})")

        print_banner("RajaBee is RUNNING. Polling for jobs...")
        self._main_loop()
        return True

    def _main_loop(self):
        """Poll KillerBee for pending jobs and process them."""
        while True:
            try:
                jobs = self.kb.get_pending_jobs(self.swarm_id)
                if jobs:
                    for job in jobs:
                        job_id = job.get("id") or job.get("job_id")
                        task = job.get("task") or job.get("prompt", "")
                        print(f"\n  [JOB {job_id}] Received: {task[:80]}...")
                        self._process_job(job_id, task)
                else:
                    print(f"  Polling... no pending jobs. "
                          f"(waiting {self.poll_interval}s)", end="\r")
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
        """Use local Ollama to split a task into major components."""
        prompt = f"""You are a SENIOR coordinator. Split this complex task into 2-4 MAJOR independent components.

RULES:
- Each component must be INDEPENDENT (can be completed without other components)
- Each component should be SUBSTANTIAL (not a simple question)
- Together, all components must fully cover the original task

The task is: {task}

Return ONLY a JSON array of strings. Example: ["component 1", "component 2"]

Your JSON array:"""

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

        prompt = f"""You are a SENIOR editor combining results from {len(component_results)} expert teams into one comprehensive final document.

The original task was: {original_task}

Here are the completed sections from each team:
{formatted}

Combine ALL sections into ONE well-organized, coherent final document.
- Integrate smoothly, do NOT just concatenate
- Remove redundancy
- Organize with clear headings and logical flow
- Keep ALL important details from every section

Your combined final document:"""

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
