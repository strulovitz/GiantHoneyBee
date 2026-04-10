"""
Worker Client -- The Worker Bee (KillerBee API)
================================================
The Worker is the bottom of the hierarchy. It does the actual AI work.

Each Worker is a SEPARATE MACHINE with its own Ollama. It connects to
KillerBee, polls for available subtasks, claims one, processes it with
local Ollama, and posts the result back.

All communication goes through the KillerBee website API.
No direct HTTP between bees. No in-process anything.

Workflow:
1. Login to KillerBee
2. Poll for available subtasks in the swarm
3. When a subtask is available: claim it
4. Use local Ollama to process the subtask
5. Post result to KillerBee
6. Go back to polling

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


class WorkerClient:
    """
    Worker Bee -- Does the actual AI work.

    Polls KillerBee for available subtasks, claims them, processes
    with local Ollama, posts results back.
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
        self.tasks_completed = 0

        self.kb = KillerBeeClient(server_url, username, password)
        self.ai = OllamaClient(base_url=ollama_url)

    def start(self):
        """Login, register, and start the main loop."""
        print_banner("Worker Bee -- The One Who Does The Work")
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
                self.swarm_id, "worker", self.model_name
            )
            self.member_id = reg_data.get("member_id", self.kb.user_id)
            print(f"  Registered as Worker (member_id={self.member_id})")
        except Exception as e:
            print(f"  [WARN] Registration: {e}")
            self.member_id = self.kb.user_id

        print_banner("Worker is RUNNING. Polling for subtasks...")
        self._main_loop()
        return True

    def _main_loop(self):
        """Poll KillerBee for available subtasks and process them."""
        while True:
            try:
                subtasks = self.kb.get_available_subtasks(self.swarm_id)
                if subtasks:
                    # Try to claim the first available subtask
                    for subtask in subtasks:
                        st_id = subtask.get("id") or subtask.get("component_id")
                        task = subtask.get("task", "")

                        # Try to claim it (another Worker might get it first)
                        try:
                            self.kb.claim_component(st_id, self.member_id)
                            print(f"\n  [SUBTASK {st_id}] Claimed: "
                                  f"{task[:80]}...")
                            self._process_subtask(st_id, task)
                            break  # Process one at a time
                        except Exception as e:
                            # Another Worker probably claimed it first
                            print(f"  [SUBTASK {st_id}] Could not claim: {e}")
                            continue
                else:
                    print(f"  Polling... no available subtasks. "
                          f"(completed: {self.tasks_completed}, "
                          f"waiting {self.poll_interval}s)", end="\r")
            except Exception as e:
                print(f"  [ERROR] Polling failed: {e}")

            time.sleep(self.poll_interval)

    def _process_subtask(self, subtask_id: int, task: str):
        """Process a single subtask using local Ollama."""
        start_time = time.time()

        print(f"  [SUBTASK {subtask_id}] Processing with {self.model_name}...")

        # Use local Ollama to process the subtask
        prompt = f"""You are a worker bee. Answer this task completely and thoroughly.

Task: {task}

Your complete answer:"""

        result = self.ai.ask(
            prompt=prompt,
            model=self.model_name,
            temperature=0.7
        )

        processing_time = time.time() - start_time

        # Post result back to KillerBee
        try:
            self.kb.post_component_result(subtask_id, result, processing_time)
            self.tasks_completed += 1
            print(f"  [SUBTASK {subtask_id}] COMPLETE in "
                  f"{processing_time:.1f}s "
                  f"(total completed: {self.tasks_completed})")
        except Exception as e:
            print(f"  [SUBTASK {subtask_id}] [ERROR] "
                  f"Failed to post result: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Worker Bee -- Does the actual AI work. "
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

    worker = WorkerClient(
        server_url=args.server,
        swarm_id=args.swarm_id,
        username=args.username,
        password=args.password,
        model_name=args.model,
        ollama_url=args.ollama_url,
        poll_interval=args.poll_interval
    )

    worker.start()


if __name__ == '__main__':
    main()
