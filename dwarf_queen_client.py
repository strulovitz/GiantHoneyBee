"""
DwarfQueen Client -- Lowest-Level Coordinator (KillerBee API)
=============================================================
Named after Apis florea (Red Dwarf Honey Bee).

The DwarfQueen is the LOWEST-level coordinator -- the only queen that
creates subtasks for Workers. She receives components from GiantQueens,
splits them into subtasks, and posts them to KillerBee for Workers to claim.

All communication goes through the KillerBee website API.
No direct HTTP between bees. No in-process Workers.

Workflow:
1. Login to KillerBee
2. Poll for assigned work (components from GiantQueens)
3. When a component arrives: use local Ollama to split into subtasks
4. Post subtasks to KillerBee (Workers will claim these)
5. Poll until all subtasks have results
6. Use local Ollama to combine subtask results
7. Post combined result to KillerBee

Hierarchy: RajaBee -> GiantQueens -> DwarfQueens -> Workers
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


class DwarfQueenClient:
    """
    DwarfQueen -- Lowest-level coordinator.

    Polls KillerBee for assigned components, splits them into subtasks
    for Workers, waits for results, combines them.
    """

    def __init__(self, server_url: str, swarm_id: int,
                 username: str, password: str,
                 model_name: str = "qwen2.5:1.5b",
                 ollama_url: str = "http://localhost:11434",
                 poll_interval: int = 5):
        self.server_url = server_url
        self.swarm_id = swarm_id
        self.model_name = model_name
        self.poll_interval = poll_interval
        self.member_id = None

        self.kb = KillerBeeClient(server_url, username, password)
        self.ai = OllamaClient(base_url=ollama_url)

    def start(self):
        """Login, register, and start the main loop."""
        print_banner("DwarfQueen -- Lowest-Level Coordinator")
        print(f"  Server:    {self.server_url}")
        print(f"  Swarm:     {self.swarm_id}")
        print(f"  Model:     {self.model_name}")
        print(f"  Username:  {self.kb.username}")

        if not self.ai.is_available():
            print("\n  [ERROR] Cannot connect to Ollama! Is it running?")
            return False
        print(f"  Ollama:    Connected ({self.ai.backend_name()})")

        try:
            self.kb.login()
            print(f"  KillerBee: Logged in (user_id={self.kb.user_id})")
        except Exception as e:
            print(f"\n  [ERROR] Cannot login to KillerBee: {e}")
            return False

        try:
            reg_data = self.kb.register_member(
                self.swarm_id, "dwarf_queen", self.model_name
            )
            self.member_id = reg_data.get("member_id", self.kb.user_id)
            print(f"  Registered as DwarfQueen (member_id={self.member_id})")
        except Exception as e:
            print(f"  [WARN] Registration: {e}")
            self.member_id = self.kb.user_id

        print_banner("DwarfQueen is RUNNING. Polling for work...")
        self._main_loop()
        return True

    def _main_loop(self):
        """Poll KillerBee for available components to claim and process."""
        while True:
            try:
                # First check for work already assigned to us
                work = self.kb.get_my_work(self.member_id)
                if work:
                    for component in work:
                        comp_id = component.get("id") or component.get("component_id")
                        task = component.get("task", "")
                        original_task = component.get("original_task", task)
                        status = component.get("status", "")
                        if status in ("pending", "assigned", ""):
                            print(f"\n  [COMPONENT {comp_id}] Assigned to me: "
                                  f"{task[:80]}...")
                            self._process_component(comp_id, task, original_task)
                else:
                    # Check for unclaimed components we can claim
                    available = self.kb.get_available_components(self.swarm_id)
                    if available:
                        for component in available:
                            comp_id = component.get("id")
                            task = component.get("task", "")
                            original_task = component.get("original_task", task)
                            try:
                                self.kb.claim_component(comp_id, self.member_id)
                                print(f"\n  [COMPONENT {comp_id}] Claimed: "
                                      f"{task[:80]}...")
                                self._process_component(comp_id, task, original_task)
                                break  # One at a time
                            except Exception as e:
                                print(f"  [COMPONENT {comp_id}] Could not claim: {e}")
                                continue
                    else:
                        print(f"  Polling... no work available. "
                              f"(waiting {self.poll_interval}s)", end="\r")
            except Exception as e:
                print(f"  [ERROR] Polling failed: {e}")

            time.sleep(self.poll_interval)

    def _process_component(self, component_id: int, task: str, original_task: str = ""):
        """Process a component: split into subtasks for Workers."""
        start_time = time.time()
        original_task = original_task or task

        # Step 1: Claim the component
        try:
            self.kb.claim_component(component_id, self.member_id)
            print(f"  [COMPONENT {component_id}] Claimed")
        except Exception as e:
            print(f"  [COMPONENT {component_id}] [WARN] Claim: {e}")

        # Step 2: Split into subtasks using local Ollama
        print(f"  [COMPONENT {component_id}] Splitting into subtasks "
              f"for Workers...")
        subtasks = self._split_into_subtasks(task, original_task)
        print(f"  [COMPONENT {component_id}] Split into "
              f"{len(subtasks)} subtasks")

        for i, st in enumerate(subtasks):
            print(f"    Subtask {i+1}: {st[:70]}...")

        # Step 3: Post subtasks to KillerBee (Workers will claim these)
        children_data = [{"task": st, "component_type": "subtask"} for st in subtasks]
        try:
            split_result = self.kb.split_component(component_id, children_data)
            print(f"  [COMPONENT {component_id}] Subtasks posted "
                  f"(Workers can now claim them)")
        except Exception as e:
            print(f"  [COMPONENT {component_id}] [ERROR] "
                  f"Failed to post subtasks: {e}")
            return

        # Step 4: Wait for all subtasks to have results
        print(f"  [COMPONENT {component_id}] Waiting for Workers...")
        child_results = self._wait_for_children(component_id, split_result)

        if not child_results:
            print(f"  [COMPONENT {component_id}] [ERROR] "
                  f"No subtask results received")
            return

        # Step 5: Combine results
        print(f"  [COMPONENT {component_id}] Combining "
              f"{len(child_results)} Worker results...")
        combined = self._combine_results(task, original_task, child_results)

        processing_time = time.time() - start_time

        # Step 6: Post combined result
        try:
            self.kb.post_component_result(
                component_id, combined, processing_time
            )
            print(f"  [COMPONENT {component_id}] COMPLETE in "
                  f"{processing_time:.1f}s")
        except Exception as e:
            print(f"  [COMPONENT {component_id}] [ERROR] "
                  f"Failed to post result: {e}")

    def _split_into_subtasks(self, task: str, original_task: str = "") -> list:
        """Use local Ollama to split a component into subtasks for Workers."""
        original_task = original_task or task
        prompt = f"""You are a team lead splitting a task into 2-4 small, specific subtasks that individual workers can complete independently.

CRITICAL CONTEXT: The ORIGINAL QUESTION that started this whole process was:
"{original_task}"

Your specific component to split into subtasks is: {task}

RULES:
- Each subtask must be SMALL and SPECIFIC (a single focused question or action)
- Each subtask must be INDEPENDENT (worker doesn't need other results)
- Together they must fully cover YOUR component
- Every subtask MUST stay relevant to the ORIGINAL QUESTION above
- Do NOT drift into unrelated topics — if the original question asks for pros and cons, the subtasks should be about pros and cons

The task to split: {task}

Return ONLY a JSON array of strings. Example: ["subtask 1", "subtask 2", "subtask 3"]

Your JSON array:"""

        result = self.ai.ask_for_json_list(
            prompt=prompt,
            model=self.model_name,
            temperature=0.3
        )

        if not result or len(result) < 2:
            result = [task]

        return result

    def _wait_for_children(self, component_id: int,
                           split_result: dict) -> list:
        """Poll until all children (subtasks) have results."""
        max_wait = 3600
        waited = 0

        while waited < max_wait:
            time.sleep(self.poll_interval)
            waited += self.poll_interval

            try:
                children = self.kb.get_children(component_id)
                if not children:
                    continue

                all_done = True
                completed_results = []

                for child in children:
                    if child.get("result"):
                        completed_results.append(child)
                    else:
                        all_done = False

                if all_done and completed_results:
                    print(f"  [COMPONENT {component_id}] All "
                          f"{len(completed_results)} subtasks completed "
                          f"after {waited}s")
                    return completed_results

                print(f"  [COMPONENT {component_id}] Waiting... "
                      f"{len(completed_results)}/{len(children)} done "
                      f"({waited}s)", end="\r")

            except Exception as e:
                print(f"  [COMPONENT {component_id}] [WARN] Poll error: {e}")

        print(f"  [COMPONENT {component_id}] [TIMEOUT] Waited {max_wait}s")
        return []

    def _combine_results(self, component_task: str, original_task: str,
                         child_results: list) -> str:
        """Use local Ollama to combine Worker results."""
        formatted = ""
        for i, cr in enumerate(child_results):
            task_desc = cr.get("task", f"Subtask {i+1}")
            result_text = cr.get("result", "[No result]")
            formatted += f"\n--- Worker {i+1}: {task_desc[:60]} ---\n"
            formatted += f"{result_text}\n"

        prompt = f"""You are combining results from {len(child_results)} workers into one coherent answer.

ORIGINAL QUESTION (what the user actually asked): {original_task}

YOUR SPECIFIC COMPONENT was: {component_task}

Worker results:
{formatted}

Combine into ONE clear, complete answer that addresses YOUR COMPONENT in the context of the ORIGINAL QUESTION.
Stay focused on what was actually asked. Integrate smoothly, remove redundancy, keep all important details.

Your combined answer:"""

        return self.ai.ask(
            prompt=prompt,
            model=self.model_name,
            temperature=0.5
        )


def main():
    parser = argparse.ArgumentParser(
        description="DwarfQueen -- Lowest-level coordinator. "
                    "Connects to KillerBee website API."
    )
    parser.add_argument('--server', type=str, required=True,
                        help='KillerBee server URL')
    parser.add_argument('--swarm-id', type=int, required=True,
                        help='Swarm ID to join')
    parser.add_argument('--username', type=str, required=True,
                        help='Username for KillerBee login')
    parser.add_argument('--password', type=str, required=True,
                        help='Password for KillerBee login')
    parser.add_argument('--model', type=str, default='qwen2.5:1.5b',
                        help='Ollama model name (default: qwen2.5:1.5b)')
    parser.add_argument('--ollama-url', type=str,
                        default='http://localhost:11434',
                        help='Ollama API URL')
    parser.add_argument('--poll-interval', type=int, default=5,
                        help='Seconds between polls (default: 5)')
    args = parser.parse_args()

    queen = DwarfQueenClient(
        server_url=args.server,
        swarm_id=args.swarm_id,
        username=args.username,
        password=args.password,
        model_name=args.model,
        ollama_url=args.ollama_url,
        poll_interval=args.poll_interval
    )

    queen.start()


if __name__ == '__main__':
    main()
