"""In-memory job registry for long-running evaluations (polled by the UI)."""
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Job:
    id: str
    owner: str
    created_at: float = field(default_factory=time.time)
    status: str = "queued"          # queued | running | done | error
    stage: str = "Queued"
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class JobStore:
    def __init__(self, ttl_seconds: int = 7200, max_jobs: int = 6) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max(1, max_jobs)

    def _prune_locked(self) -> None:
        now = time.time()
        for jid in [j.id for j in self._jobs.values() if now - j.created_at > self._ttl and j.status in ("done", "error")]:
            self._jobs.pop(jid, None)
        # keep memory bounded: drop the oldest finished jobs first
        finished = sorted((j for j in self._jobs.values() if j.status in ("done", "error")), key=lambda j: j.created_at)
        while len(self._jobs) > self._max and finished:
            self._jobs.pop(finished.pop(0).id, None)

    def create(self, owner: str) -> Job:
        with self._lock:
            self._prune_locked()
            job = Job(id=uuid.uuid4().hex, owner=owner)
            self._jobs[job.id] = job
            return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status in ("queued", "running"))
