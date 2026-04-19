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
from photo_tier import process_photo_piece
from audio_tier import process_audio_piece
from tier_timeouts import TIMEOUTS, CIRCUIT_BREAKER

# Whisper model path for Worker (plan Section 6b — same as DwarfQueen: tiny)
_WORKER_WHISPER_MODEL = str(
    __import__('pathlib').Path.home()
    / "multimedia-feasibility" / "whisper.cpp" / "models"
    / "ggml-tiny.bin"
)


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

        self.ollama_url = ollama_url
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
        """Poll KillerBee for work: assigned tasks first, then available subtasks."""
        while True:
            try:
                found_work = False

                # First: check for tasks assigned DIRECTLY to me
                # (includes calibration tasks from my boss)
                my_work = self.kb.get_my_work(self.member_id)
                if my_work:
                    for task_item in my_work:
                        t_id = task_item.get("id") or task_item.get("component_id")
                        task = task_item.get("task", "")
                        original_task = task_item.get("original_task", task)
                        comp_type = task_item.get("component_type", "subtask")
                        piece_path = task_item.get("piece_path")
                        media_type = task_item.get("media_type")
                        print(f"\n  [TASK {t_id}] Assigned to me ({comp_type}):")
                        print(f"  FULL QUESTION:")
                        print(f"  ---BEGIN---")
                        print(f"  {task}")
                        print(f"  ---END---")
                        self._process_subtask(t_id, task, original_task,
                                              piece_path=piece_path,
                                              media_type=media_type,
                                              job_id=task_item.get("job_id"))
                        found_work = True
                        break  # One at a time

                # Second: check for unclaimed subtasks
                if not found_work:
                    subtasks = self.kb.get_available_subtasks(self.swarm_id)
                    if subtasks:
                        for subtask in subtasks:
                            st_id = subtask.get("id") or subtask.get("component_id")
                            task = subtask.get("task", "")
                            original_task = subtask.get("original_task", task)
                            piece_path = subtask.get("piece_path")
                            media_type = subtask.get("media_type")

                            try:
                                self.kb.claim_component(st_id, self.member_id)
                                print(f"\n  [SUBTASK {st_id}] Claimed: "
                                      f"{task[:80]}...")
                                self._process_subtask(st_id, task, original_task,
                                                      piece_path=piece_path,
                                                      media_type=media_type,
                                                      job_id=subtask.get("job_id"))
                                found_work = True
                                break  # One at a time
                            except Exception as e:
                                print(f"  [SUBTASK {st_id}] Could not claim: {e}")
                                continue

                if not found_work:
                    print(f"  Polling... no work available. "
                          f"(completed: {self.tasks_completed}, "
                          f"waiting {self.poll_interval}s)", end="\r")
            except Exception as e:
                print(f"  [ERROR] Polling failed: {e}")

            time.sleep(self.poll_interval)

    def _process_subtask(self, subtask_id: int, task: str,
                         original_task: str = "", piece_path: str = None,
                         media_type: str = None, job_id: int = None):
        """Process a single subtask: photo tile branch or text branch."""
        start_time = time.time()
        original_task = original_task or task
        _cb_ceiling = CIRCUIT_BREAKER["worker"]  # 360s wall-clock ceiling

        # ── Photo branch ───────────────────────────────────────────────────────
        if media_type == 'photo' and piece_path:
            print(f"  [SUBTASK {subtask_id}] PHOTO tile — running vision with qwen3.5:0.8b")
            try:
                gestalt = process_photo_piece(
                    tier='worker',
                    component_id=subtask_id,
                    job_id=job_id,
                    piece_url=piece_path,
                    vision_model='qwen3.5:0.8b',
                    text_model=None,
                    resize_spec=(384, 384),
                    client=self.kb,
                    ollama_url=self.ollama_url,
                )
            except Exception as e:
                print(f"  [SUBTASK {subtask_id}] [ERROR] Photo vision: {e}")
                return
            processing_time = time.time() - start_time
            print(f"  [SUBTASK {subtask_id}] PHOTO TILE RESULT: {gestalt[:120]}...")
            try:
                self.kb.post_component_result(subtask_id, gestalt, processing_time)
                self.tasks_completed += 1
                print(f"  [SUBTASK {subtask_id}] PHOTO TILE COMPLETE in "
                      f"{processing_time:.1f}s "
                      f"(total completed: {self.tasks_completed})")
            except Exception as e:
                print(f"  [SUBTASK {subtask_id}] [ERROR] Failed to post result: {e}")
            return
        # ──────────────────────────────────────────────────────────────────────

        # ── Audio branch ───────────────────────────────────────────────────────
        if media_type == 'audio' and piece_path:
            print(f"  [SUBTASK {subtask_id}] AUDIO slice — running whisper-tiny")
            try:
                transcription = process_audio_piece(
                    tier='worker',
                    component_id=subtask_id,
                    job_id=job_id,
                    piece_url=piece_path,
                    whisper_model_path=_WORKER_WHISPER_MODEL,
                    text_model=None,     # Worker is leaf — STT output IS the result
                    client=self.kb,
                    ollama_url=self.ollama_url,
                )
            except Exception as e:
                print(f"  [SUBTASK {subtask_id}] [ERROR] Audio whisper: {e}")
                return
            processing_time = time.time() - start_time
            print(f"  [SUBTASK {subtask_id}] AUDIO SLICE RESULT: {transcription[:120]}...")
            try:
                self.kb.post_component_result(subtask_id, transcription, processing_time)
                self.tasks_completed += 1
                print(f"  [SUBTASK {subtask_id}] AUDIO SLICE COMPLETE in "
                      f"{processing_time:.1f}s "
                      f"(total completed: {self.tasks_completed})")
            except Exception as e:
                print(f"  [SUBTASK {subtask_id}] [ERROR] Failed to post result: {e}")
            return
        # ──────────────────────────────────────────────────────────────────────

        # ── Circuit breaker: wall-clock ceiling check ──────────────────────────
        elapsed = time.time() - start_time
        if elapsed > _cb_ceiling:
            print(f"  [CIRCUIT BREAKER] subtask {subtask_id} exceeded "
                  f"{_cb_ceiling}s wall clock ({elapsed:.0f}s elapsed) — releasing")
            return
        # ──────────────────────────────────────────────────────────────────────

        # ── Text branch (existing Phase 3 logic, unchanged) ───────────────────
        print(f"  [SUBTASK {subtask_id}] Processing with {self.model_name}...")

        # Use local Ollama to process the subtask
        prompt = f"""{task}

Context: this is part of a larger question: "{original_task}" """

        print(f"  [SUBTASK {subtask_id}] FULL PROMPT TO LLM:")
        print(f"  ---BEGIN PROMPT---")
        print(f"  {prompt}")
        print(f"  ---END PROMPT---")

        result = self.ai.ask(
            prompt=prompt,
            model=self.model_name,
            temperature=0.7,
            timeout_sec=TIMEOUTS["text_integration"],
        )

        processing_time = time.time() - start_time

        print(f"  [SUBTASK {subtask_id}] FULL ANSWER:")
        print(f"  ---BEGIN---")
        print(f"  {result}")
        print(f"  ---END---")

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
    parser.add_argument('--server', type=str,
                        default=os.environ.get('KILLERBEE_URL'),
                        help='KillerBee server URL (env: KILLERBEE_URL)')
    parser.add_argument('--swarm-id', type=int,
                        default=int(os.environ.get('KILLERBEE_SWARM_ID', '1')),
                        help='Swarm ID (env: KILLERBEE_SWARM_ID, default 1)')
    parser.add_argument('--username', type=str,
                        default=os.environ.get('KILLERBEE_USERNAME'),
                        help='Username (env: KILLERBEE_USERNAME)')
    parser.add_argument('--password', type=str,
                        default=os.environ.get('KILLERBEE_PASSWORD'),
                        help='Password (env: KILLERBEE_PASSWORD)')
    parser.add_argument('--model', type=str,
                        default=os.environ.get('KILLERBEE_MODEL', 'qwen3:1.7b'),
                        help='Ollama model (env: KILLERBEE_MODEL, tier default qwen3:1.7b)')
    parser.add_argument('--ollama-url', type=str,
                        default=os.environ.get('OLLAMA_URL', 'http://localhost:11434'),
                        help='Ollama API URL (env: OLLAMA_URL)')
    parser.add_argument('--poll-interval', type=int, default=5,
                        help='Seconds between polls (default: 5)')
    args = parser.parse_args()

    missing = [k for k in ('server', 'username', 'password') if getattr(args, k) is None]
    if missing:
        parser.error("Missing " + ", ".join('--' + m for m in missing)
                     + " (or env KILLERBEE_URL / KILLERBEE_USERNAME / KILLERBEE_PASSWORD)")

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
