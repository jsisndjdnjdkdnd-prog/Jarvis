from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

JobCallback = Callable[[], None]


@dataclass(order=True)
class _ScheduledJob:
    run_at: float
    sequence: int
    job_id: str = field(compare=False)
    callback: JobCallback = field(compare=False)
    interval: float | None = field(default=None, compare=False)


class Scheduler:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._jobs: list[_ScheduledJob] = []
        self._cancelled: set[str] = set()
        self._sequence = itertools.count()
        self._condition = threading.Condition()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._running = False
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def schedule_in(self, job_id: str, delay_seconds: float, callback: JobCallback) -> None:
        self._push(job_id, self._clock() + max(0.0, delay_seconds), callback, None)

    def schedule_every(self, job_id: str, interval_seconds: float, callback: JobCallback) -> None:
        self._push(job_id, self._clock() + interval_seconds, callback, interval_seconds)

    def cancel(self, job_id: str) -> None:
        with self._condition:
            self._cancelled.add(job_id)
            self._condition.notify_all()

    def _push(
        self, job_id: str, run_at: float, callback: JobCallback, interval: float | None
    ) -> None:
        with self._condition:
            self._cancelled.discard(job_id)
            heapq.heappush(
                self._jobs,
                _ScheduledJob(run_at, next(self._sequence), job_id, callback, interval),
            )
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            job = self._next_due_job()
            if job is None:
                return
            self._execute(job)

    def _next_due_job(self) -> _ScheduledJob | None:
        with self._condition:
            while self._running:
                self._drop_cancelled_head()
                if not self._jobs:
                    self._condition.wait()
                    continue
                delay = self._jobs[0].run_at - self._clock()
                if delay > 0:
                    self._condition.wait(timeout=min(delay, 1.0))
                    continue
                return heapq.heappop(self._jobs)
            return None

    def _drop_cancelled_head(self) -> None:
        while self._jobs and self._jobs[0].job_id in self._cancelled:
            removed = heapq.heappop(self._jobs)
            if not any(job.job_id == removed.job_id for job in self._jobs):
                self._cancelled.discard(removed.job_id)

    def _execute(self, job: _ScheduledJob) -> None:
        try:
            job.callback()
        except Exception:
            logger.exception("Завдання планувальника %s завершилось помилкою", job.job_id)
        if job.interval is None:
            return
        with self._condition:
            if job.job_id in self._cancelled:
                return
        self._push(job.job_id, self._clock() + job.interval, job.callback, job.interval)
