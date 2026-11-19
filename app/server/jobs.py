"""Background job queue: one worker, so heavy models never compete for the GPU."""
import logging
import queue
import threading
import time
import traceback
import uuid

log = logging.getLogger("vts.jobs")


class Job:
    def __init__(self, kind: str, title: str, fn, project_id=None):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.title, self.fn, self.project_id = kind, title, fn, project_id
        self.status = "queued"  # queued | running | done | failed | cancelled
        self.stage = "Waiting"
        self.progress = 0.0
        self.error = None
        self.notes = []
        self.created = time.time()
        self.started = None
        self.finished = None
        self.cancel = threading.Event()

    def set(self, stage=None, progress=None):
        if stage is not None:
            self.stage = stage
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))

    def to_dict(self):
        eta = None
        if self.status == "running" and self.started and self.progress > 0.03:
            el = time.time() - self.started
            eta = int(el / self.progress - el)
        return {"id": self.id, "kind": self.kind, "title": self.title, "status": self.status, "stage": self.stage,
                "progress": round(self.progress, 3), "error": self.error, "notes": self.notes, "eta": eta,
                "project_id": self.project_id, "created": self.created}


class Queue:
    def __init__(self):
        self.q = queue.Queue()
        self.jobs: dict[str, Job] = {}
        self.paused = threading.Event()
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self._run, name="vts-worker", daemon=True)
        self.worker.start()

    def submit(self, job: Job) -> Job:
        self.jobs[job.id] = job
        self.q.put(job)
        return job

    def cancel(self, jid: str):
        j = self.jobs.get(jid)
        if j and j.status in ("queued", "running"):
            j.cancel.set()
            if j.status == "queued":
                j.status, j.stage = "cancelled", "Cancelled"

    def list(self):
        js = sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)[:100]
        return [j.to_dict() for j in js]

    def clear_finished(self):
        for k in [k for k, j in self.jobs.items() if j.status in ("done", "failed", "cancelled")]:
            del self.jobs[k]

    def _run(self):
        while not self.stopping.is_set():
            try:
                job = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            while self.paused.is_set() and not self.stopping.is_set() and not job.cancel.is_set():
                time.sleep(0.3)
            if job.cancel.is_set():
                job.status, job.stage = "cancelled", "Cancelled"
                continue
            job.status, job.started = "running", time.time()
            try:
                job.fn(job)
                if job.cancel.is_set():
                    job.status, job.stage = "cancelled", "Cancelled"
                else:
                    job.status, job.stage, job.progress = "done", "Finished", 1.0
            except Exception as e:  # noqa: BLE001
                if job.cancel.is_set():
                    job.status, job.stage = "cancelled", "Cancelled"
                else:
                    job.status, job.stage, job.error = "failed", "Failed", str(e) or e.__class__.__name__
                    log.error("Job %s failed: %s", job.title, traceback.format_exc())
            finally:
                job.finished = time.time()


QUEUE = Queue()
