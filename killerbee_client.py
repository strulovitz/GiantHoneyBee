"""
KillerBee API Client
====================
HTTP client for the KillerBee website API.
All bees (RajaBee, GiantQueen, DwarfQueen, Worker) use this client
to communicate through the central KillerBee server.

No direct HTTP between bees. Everything goes through KillerBee.
"""

import io
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

    def get_available_components(self, swarm_id: int,
                                    level: int = None) -> list:
        """Get unclaimed components available for GiantQueens/DwarfQueens.

        Pass level=0 for GiantQueens (claim Raja's level-0 components),
        level=1 for DwarfQueens (claim GQ's level-1 components).
        Omit level to receive all levels (backward-compatible).
        """
        params = {}
        if level is not None:
            params['level'] = level
        data = self._request("GET", f"/api/swarm/{swarm_id}/components/available",
                             params=params)
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

    # ── Multimedia ────────────────────────────────────────────────────

    def get_job_media(self, job_id: int) -> dict:
        """Return media_type and media_url for a job (may be None for text jobs)."""
        # Pending-jobs endpoint includes media fields; fetch status via job status
        # API. There's no /api/job/<id>/status endpoint, so we fetch via the
        # component-status approach — but for the job itself we just need the
        # two media fields which the pending jobs list already carries. Callers
        # who hold a job dict (from get_pending_jobs) should read media_type /
        # media_url directly from that dict. This helper is for callers who
        # only know the job_id and need to look it up separately.
        data = self._request("GET", f"/api/job/{job_id}/status")
        return {
            "media_type": data.get("media_type"),
            "media_url": data.get("media_url"),
        }

    def download_piece(self, relative_url: str) -> bytes:
        """Download a media piece from the server's /uploads/ endpoint.

        relative_url is a server-relative path such as
        'photo/swarmjob_42/cut_by_raja/grid_a_q1.jpg'.
        Leading slashes are stripped.
        No auth required on /uploads/ (served as static-like files).
        """
        relative_url = relative_url.lstrip('/')
        url = f"{self.server_url}/uploads/{relative_url}"
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.get(url, timeout=60)
                if resp.status_code >= 400:
                    raise Exception(
                        f"HTTP {resp.status_code} downloading {url}: {resp.text[:200]}"
                    )
                return resp.content
            except requests.exceptions.ConnectionError as e:
                if attempt < self.max_retries:
                    print(f"  [RETRY {attempt}/{self.max_retries}] Download error: {e}")
                    time.sleep(self.retry_delay * attempt)
                else:
                    raise Exception(f"download_piece failed after {self.max_retries} attempts: {e}")
            except requests.exceptions.Timeout as e:
                if attempt < self.max_retries:
                    print(f"  [RETRY {attempt}/{self.max_retries}] Download timeout: {e}")
                    time.sleep(self.retry_delay * attempt)
                else:
                    raise Exception(f"download_piece timed out after {self.max_retries} attempts: {e}")
        raise Exception("download_piece: unexpected exit from retry loop")

    def upload_piece(self, component_id: int, piece_path: str,
                     image_bytes: bytes) -> dict:
        """Upload a cut piece (photo tile) to the server.

        Multipart POST to /api/component/<id>/upload-piece.
        Requires Bearer auth.
        """
        url = self._url(f"/api/component/{component_id}/upload-piece")
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        files = {
            "piece": (piece_path.split("/")[-1], io.BytesIO(image_bytes), "image/jpeg"),
        }
        data = {"piece_path": piece_path}
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(url, headers=headers, files=files, data=data,
                                     timeout=60)
                if resp.status_code >= 400:
                    raise Exception(
                        f"HTTP {resp.status_code} uploading piece to component "
                        f"{component_id}: {resp.text[:200]}"
                    )
                return resp.json()
            except requests.exceptions.ConnectionError as e:
                if attempt < self.max_retries:
                    print(f"  [RETRY {attempt}/{self.max_retries}] Upload error: {e}")
                    time.sleep(self.retry_delay * attempt)
                else:
                    raise
            except requests.exceptions.Timeout as e:
                if attempt < self.max_retries:
                    print(f"  [RETRY {attempt}/{self.max_retries}] Upload timeout: {e}")
                    time.sleep(self.retry_delay * attempt)
                else:
                    raise

    def upload_piece_with_audio(self, component_id: int, piece_path: str,
                                video_bytes: bytes, audio_piece_path: str,
                                audio_bytes: bytes) -> dict:
        """Upload a video piece with its matching audio slice.

        Used for video components. Both video and audio bytes are uploaded
        in a single multipart POST.
        """
        url = self._url(f"/api/component/{component_id}/upload-piece")
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        files = {
            "piece": (piece_path.split("/")[-1], io.BytesIO(video_bytes), "video/mp4"),
            "audio_piece": (audio_piece_path.split("/")[-1], io.BytesIO(audio_bytes), "audio/mpeg"),
        }
        data = {
            "piece_path": piece_path,
            "audio_piece_path": audio_piece_path,
        }
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(url, headers=headers, files=files, data=data,
                                     timeout=120)
                if resp.status_code >= 400:
                    raise Exception(
                        f"HTTP {resp.status_code} uploading piece+audio to component "
                        f"{component_id}: {resp.text[:200]}"
                    )
                return resp.json()
            except requests.exceptions.ConnectionError as e:
                if attempt < self.max_retries:
                    print(f"  [RETRY {attempt}/{self.max_retries}] Upload+audio error: {e}")
                    time.sleep(self.retry_delay * attempt)
                else:
                    raise
            except requests.exceptions.Timeout as e:
                if attempt < self.max_retries:
                    print(f"  [RETRY {attempt}/{self.max_retries}] Upload+audio timeout: {e}")
                    time.sleep(self.retry_delay * attempt)
                else:
                    raise

    def create_child_component(self, parent_id: int | None, job_id: int,
                               task_description: str, level: int,
                               piece_path: str,
                               component_type: str = "component") -> int:
        """Create a single child JobComponent and return its id.

        Uses the POST /api/component/create-child endpoint (added in
        commit for multimedia support). Auth required.
        """
        data = self._request("POST", "/api/component/create-child", {
            "parent_id": parent_id,
            "job_id": job_id,
            "task_description": task_description,
            "level": level,
            "piece_path": piece_path,
            "component_type": component_type,
        })
        comp_id = data.get("component_id")
        if comp_id is None:
            raise Exception(f"create_child_component: no component_id in response: {data}")
        return comp_id

    def get_children_results(self, parent_component_id: int,
                             timeout_sec: int = 1800,
                             poll_interval: int = 5) -> list:
        """Poll until all children of parent_component_id are completed.

        Returns list of (piece_stem, result_text) tuples — 8 entries for a
        full Grid A + Grid B cut. Raises TimeoutError if children do not
        complete within timeout_sec.

        Done condition: child['status'] == 'completed', regardless of whether
        result is empty. If the result is empty (e.g. vision model timed out
        and returned nothing), we use the placeholder '[gestalt returned empty]'
        so the integrator never receives None and the pipeline does not stall
        waiting for a result that will never arrive.
        """
        import os as _os
        waited = 0
        while waited < timeout_sec:
            time.sleep(poll_interval)
            waited += poll_interval
            try:
                children = self.get_children(parent_component_id)
                if not children:
                    continue
                all_done = True
                results = []
                for child in children:
                    if child.get("status") == "completed":
                        piece_path = child.get("task", "")
                        stem = (_os.path.splitext(_os.path.basename(piece_path))[0]
                                if piece_path else f"child_{child['id']}")
                        result_text = child.get("result") or "[gestalt returned empty]"
                        results.append((stem, result_text))
                    else:
                        all_done = False
                if all_done and results:
                    return results
                print(f"  [get_children_results parent={parent_component_id}] "
                      f"{len(results)}/{len(children)} done ({waited}s)", end="\r")
            except Exception as e:
                print(f"  [get_children_results] poll error: {e}")

        raise TimeoutError(
            f"get_children_results: parent={parent_component_id} "
            f"timed out after {timeout_sec}s"
        )

    def update_job_status(self, job_id: int, status: str) -> dict:
        """Update the status of a SwarmJob (e.g. 'splitting', 'processing').

        Hits POST /api/job/<id>/update with {"status": status}.
        Used by RajaBee to mark a job as claimed so the poll loop does not
        re-pick the same job on the next iteration.
        """
        return self._request("POST", f"/api/job/{job_id}/update", {
            "status": status
        })

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
