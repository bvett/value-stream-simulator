"""Bounded model subprocesses for responsive HTTP job handling."""

import json
import subprocess
import sys
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from uuid import UUID

from .job_store import JobNotFound, JobStorage
from .schemas import JobRequest, ModelError, ResultData
from .settings import ServiceSettings


class ModelScheduler:
    def __init__(self, store: JobStorage, settings: ServiceSettings):
        self.store = store
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=settings.max_model_workers)
        self._lock = threading.RLock()
        self._futures: dict[UUID, list[Future]] = {}
        self._active_jobs: set[UUID] = set()
        self._pending_jobs: deque[tuple[UUID, JobRequest]] = deque()
        self._processes: dict[tuple[UUID, int], subprocess.Popen] = {}
        self._closed = False

    def submit(self, job_id: UUID, request: JobRequest) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("scheduler is closed")
            if len(self._active_jobs) >= self.settings.max_active_jobs:
                self._pending_jobs.append((job_id, request))
            else:
                self._active_jobs.add(job_id)
                self._start_job(job_id, request)

    def _start_job(self, job_id: UUID, request: JobRequest) -> None:
        futures = [
            self._executor.submit(self._run_model, job_id, request, index)
            for index in range(len(request.models))
        ]
        self._futures[job_id] = futures
        for future in futures:
            future.add_done_callback(lambda _done, job=job_id: self._forget_finished(job))

    def _forget_finished(self, job_id: UUID) -> None:
        with self._lock:
            futures = self._futures.get(job_id)
            if futures is not None and all(future.done() for future in futures):
                del self._futures[job_id]
                self._active_jobs.discard(job_id)
                while not self._closed and self._pending_jobs and (
                    len(self._active_jobs) < self.settings.max_active_jobs
                ):
                    next_id, next_request = self._pending_jobs.popleft()
                    try:
                        if self.store.status(next_id).status == "cancelled":
                            continue
                    except JobNotFound:
                        continue
                    self._active_jobs.add(next_id)
                    self._start_job(next_id, next_request)

    def _run_model(self, job_id: UUID, request: JobRequest, index: int) -> None:
        try:
            if not self.store.start_model(job_id, index):
                return
        except JobNotFound:
            return
        payload = {
            "model_index": index,
            "max_outcome_bytes": self.settings.max_model_outcome_bytes,
            "request": {
                "tasks": [t.model_dump(mode="json") for t in request.tasks],
                "models": [request.models[index].model_dump(mode="json")],
                "seed": request.seed,
            },
        }
        result = None
        error = None
        process = None
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "value_stream.service.worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            with self._lock:
                self._processes[(job_id, index)] = process
                cancelled = self.store.status(job_id).status == "cancelled"
            if cancelled:
                process.terminate()
                return
            stdout, stderr = process.communicate(
                input=json.dumps(payload, allow_nan=False).encode("utf-8"),
                timeout=self.settings.max_model_seconds,
            )
            if process.returncode != 0:
                raise RuntimeError("model worker exited unexpectedly")
            if len(stdout) > self.settings.max_model_outcome_bytes + 4096:
                raise ValueError("model result exceeds configured size limit")
            output = json.loads(stdout)
            if "result" in output:
                result = ResultData.model_validate(output["result"])
                if result.model_index != index:
                    raise ValueError("worker returned the wrong model index")
            elif "error" in output:
                error = ModelError.model_validate(output["error"])
                if error.model_index != index:
                    raise ValueError("worker returned the wrong model index")
            else:
                raise ValueError("worker did not return a model outcome")
        except subprocess.TimeoutExpired:
            error = ModelError(
                model_index=index, code="MODEL_TIMEOUT", message="model exceeded time limit"
            )
            self._stop_process(process)
        except Exception as exc:
            error = ModelError(
                model_index=index, code="WORKER_FAILED", message=str(exc)
            )
            self._stop_process(process)
        finally:
            with self._lock:
                self._processes.pop((job_id, index), None)
            if process is not None and process.poll() is None:
                self._stop_process(process)
            try:
                self.store.finish_model(job_id, index, result=result, error=error)
            except JobNotFound:
                pass

    @staticmethod
    def _stop_process(process: subprocess.Popen | None) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()

    def cancel(self, job_id: UUID) -> None:
        self.store.cancel(job_id)
        with self._lock:
            self._pending_jobs = deque(
                (pending_id, request)
                for pending_id, request in self._pending_jobs
                if pending_id != job_id
            )
            for future in self._futures.get(job_id, []):
                future.cancel()
            processes = [
                process
                for (running_job, _), process in self._processes.items()
                if running_job == job_id
            ]
        for process in processes:
            if process.poll() is None:
                process.terminate()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            job_ids = list(self._futures) + [job_id for job_id, _ in self._pending_jobs]
        for job_id in job_ids:
            try:
                self.cancel(job_id)
            except JobNotFound:
                pass
        self._executor.shutdown(wait=True, cancel_futures=True)
