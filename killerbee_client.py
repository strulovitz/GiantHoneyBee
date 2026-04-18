"""
KillerBee API Client
====================
HTTP client for the KillerBee website API.
All bees (RajaBee, GiantQueen, DwarfQueen, Worker) use this client
to communicate through the central KillerBee server.

No direct HTTP between bees. Everything goes through KillerBee.
"""

import time
import requests


class KillerBeeClient:
    """Client for the KillerBee website API."""

    def __init__(self, server_url: str, username: str, password: str,
                 max_retries: int = 10, retry_delay: float = 2.0):
        self.server_url = server_url.rstrip('/')
        self.username = username
        self.password = password
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.token = None
        self.user_id = None

    def _url(self, path: str) -> str:
        return f"{self.server_url}{path}"

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, json_data: dict = None,
                 params: dict = None) -> dict:
        """Make an HTTP request with retry logic."""
        url = self._url(path)
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.request(
                    method, url,
                    json=json_data,
                    params=params,
                    headers=self._headers(),
                    timeout=30
                )
                if resp.status_code >= 400:
                    error_text = resp.text
                    raise Exception(
                        f"HTTP {resp.status_code} from {method} {path}: {error_text}"
                    )
                return resp.json()
            except requests.exceptions.ConnectionError as e:
                last_error = e
                if attempt < self.max_retries:
                    print(f"  [RETRY {attempt}/{self.max_retries}] Connection error to {url}: {e}")
                    time.sleep(self.retry_delay * attempt)
            except requests.exceptions.Timeout as e:
                last_error = e
                if attempt < self.max_retries:
                    print(f"  [RETRY {attempt}/{self.max_retries}] Timeout on {url}: {e}")
                    time.sleep(self.retry_delay * attempt)

        raise Exception(f"Failed after {self.max_retries} attempts: {last_error}")

    # ── Auth ──────────────────────────────────────────────────────────

    def login(self) -> dict:
        """Login to KillerBee and store the auth token."""
        data = self._request("POST", "/api/auth/login", {
            "username": self.username,
            "password": self.password
        })
        self.token = data.get("token")
        self.user_id = data.get("user_id")
        return data

    # ── Registration ──────────────────────────────────────────────────

    def register_member(self, swarm_id: int, member_type: str,
                        model: str) -> dict:
        """Register this bee as a member of a swarm."""
        return self._request("POST", f"/api/swarm/{swarm_id}/register", {
            "username": self.username,
            "password": self.password,
            "member_type": member_type,
            "model": model
        })

    # ── Jobs (RajaBee level) ──────────────────────────────────────────

    def get_pending_jobs(self, swarm_id: int) -> list:
        """Get pending jobs for a swarm."""
        data = self._request("GET", f"/api/swarm/{swarm_id}/jobs/pending")
        return data if isinstance(data, list) else data.get("jobs", [])

    def split_job(self, job_id: int, components: list) -> dict:
        """Split a job into components."""
        return self._request("POST", f"/api/job/{job_id}/split", {
            "components": components
        })

    def post_job_result(self, job_id: int, result: str,
                        total_time: float) -> dict:
        """Post the final combined result for a job."""
        return self._request("POST", f"/api/job/{job_id}/result", {
            "result": result,
            "total_time": total_time
        })

    # ── Components (Queen level) ──────────────────────────────────────

    def get_my_work(self, member_id: int) -> list:
        """Get components assigned to this member."""
        data = self._request("GET", f"/api/member/{member_id}/work")
        return data if isinstance(data, list) else data.get("components", [])

    def claim_component(self, component_id: int, member_id: int) -> dict:
        """Claim a component for processing."""
        return self._request("POST", f"/api/component/{component_id}/claim", {
            "member_id": member_id
        })

    def split_component(self, component_id: int, children: list) -> dict:
        """Split a component into child sub-components."""
        return self._request("POST", f"/api/component/{component_id}/split", {
            "children": children
        })

    def get_children(self, component_id: int) -> list:
        """Get child components and their results."""
        data = self._request("GET", f"/api/component/{component_id}/children")
        return data if isinstance(data, list) else data.get("children", [])

    def post_component_result(self, component_id: int, result: str,
                              processing_time: float) -> dict:
        """Post the result for a component."""
        return self._request("POST", f"/api/component/{component_id}/result", {
            "result": result,
            "processing_time": processing_time
        })

    # ── Subtasks (Worker level) ───────────────────────────────────────

    def get_available_subtasks(self, swarm_id: int) -> list:
        """Get unclaimed subtasks available for Workers."""
        data = self._request("GET", f"/api/swarm/{swarm_id}/subtasks/available")
        return data if isinstance(data, list) else data.get("subtasks", [])

    def get_available_components(self, swarm_id: int) -> list:
        """Get unclaimed components available for GiantQueens/DwarfQueens."""
        data = self._request("GET", f"/api/swarm/{swarm_id}/components/available")
        return data if isinstance(data, list) else data.get("components", [])

    # ── Buzzing (Performance Calibration) ────────────────────────────

    def get_subordinates(self, member_id: int) -> list:
        """Get list of subordinates for a member."""
        data = self._request("GET", f"/api/member/{member_id}/subordinates")
        return data if isinstance(data, list) else data.get("subordinates", [])

    def get_unassigned_members(self, swarm_id: int, member_type: str) -> list:
        """Get unassigned members of a given type in a swarm."""
        data = self._request(
            "GET", f"/api/swarm/{swarm_id}/unassigned",
            params={"type": member_type}
        )
        return data if isinstance(data, list) else data.get("unassigned", [])

    def claim_subordinate(self, member_id: int,
                          subordinate_member_id: int) -> dict:
        """Claim an unassigned member as a subordinate."""
        return self._request("POST", f"/api/member/{member_id}/claim-subordinate", {
            "subordinate_member_id": subordinate_member_id
        })

    def report_buzzing(self, member_id: int, buzzing_speed: float,
                       buzzing_quality: float,
                       reporter_member_id: int) -> dict:
        """Report buzzing scores for a subordinate."""
        return self._request("POST", f"/api/member/{member_id}/buzzing", {
            "buzzing_speed": buzzing_speed,
            "buzzing_quality": buzzing_quality,
            "reporter_member_id": reporter_member_id
        })

    def recalculate_member(self, member_id: int) -> dict:
        """Recalculate capacity and fractions for a member."""
        return self._request("POST", f"/api/member/{member_id}/recalculate")

    def get_fractions(self, member_id: int) -> dict:
        """Get subordinates with their fractions for splitting work."""
        data = self._request("GET", f"/api/member/{member_id}/fractions")
        return data

    # ── Heartbeat ─────────────────────────────────────────────────────

    def heartbeat(self, swarm_id: int, member_id: int,
                  capabilities: dict = None) -> dict:
        """Send a heartbeat to KillerBee."""
        payload = {
            "swarm_id": swarm_id,
            "member_id": member_id
        }
        if capabilities:
            payload["capabilities"] = capabilities
        return self._request("POST", f"/api/member/{member_id}/heartbeat",
                             payload)
