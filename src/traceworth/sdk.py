from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Lock, Thread
from time import perf_counter
from typing import Callable
from uuid import uuid4

from .validation import label, positive_integer, scalar, usage


class JsonlExporter:
    """Append event envelopes to a local file; called by the SDK worker."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def __call__(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, allow_nan=False) + "\n")


@dataclass(frozen=True)
class _Context:
    workflow_id: str
    step_id: str


class TraceWorth:
    """An isolated SDK client. Use one per application process.

    Export failures never propagate into instrumented application code. Explicit
    recording APIs validate caller-supplied metadata. No arguments, return values,
    exception messages, prompts, or credentials are collected automatically.
    """

    def __init__(self, application: str, exporter: Callable[[dict], None], *,
                 environment: str = "development", configuration_id: str | None = None,
                 queue_size: int = 1024):
        label(application, "application")
        label(environment, "environment")
        label(configuration_id, "configuration_id", nullable=True)
        positive_integer(queue_size, "queue_size")
        if not callable(exporter):
            raise ValueError("exporter must be callable")
        self.application = application
        self.environment = environment
        self.configuration_id = configuration_id
        self._exporter = exporter
        self._context: ContextVar[_Context | None] = ContextVar(
            f"traceworth_{id(self)}", default=None)
        self._queue: Queue = Queue(maxsize=queue_size)
        self._lock = Lock()
        self._closed = False
        self._pending = 0
        self._dropped = 0
        self._export_errors = 0
        self._worker = Thread(target=self._run, daemon=True, name="traceworth-export")
        self._worker.start()

    @property
    def diagnostics(self) -> dict:
        with self._lock:
            return {"pending_events": self._pending, "dropped_events": self._dropped,
                    "export_errors": self._export_errors}

    def _run(self):
        while True:
            try:
                event = self._queue.get(timeout=0.05)
            except Empty:
                with self._lock:
                    if self._closed:
                        return
                continue
            try:
                self._exporter(event)
            except Exception:
                with self._lock:
                    self._export_errors += 1
            finally:
                with self._lock:
                    self._pending -= 1
                self._queue.task_done()

    def _emit(self, event_type: str, **fields):
        current = self._context.get()
        event = {"schema_version": 1, "event_id": str(uuid4()),
                 "event_type": event_type,
                 "occurred_at": datetime.now(timezone.utc).isoformat(),
                 "application_id": self.application, "environment": self.environment,
                 "configuration_id": self.configuration_id,
                 "workflow_id": current.workflow_id if current else None,
                 "step_id": current.step_id if current else None, **fields}
        with self._lock:
            if self._closed:
                self._dropped += 1
                return
            try:
                self._queue.put_nowait(event)
                self._pending += 1
            except Full:
                self._dropped += 1

    @contextmanager
    def span(self, name: str, *, workflow: bool = False, attempt_number: int = 1):
        """Measure a block. A standalone operation creates its own workflow ID."""
        label(name, "name")
        positive_integer(attempt_number, "attempt_number")
        if type(workflow) is not bool:
            raise ValueError("workflow must be boolean")
        parent = self._context.get()
        current = _Context(str(uuid4()) if workflow or parent is None else parent.workflow_id,
                           str(uuid4()))
        token = self._context.set(current)
        common = {"name": name, "kind": "workflow" if workflow else "operation",
                  "parent_step_id": parent.step_id if parent and not workflow else None,
                  "attempt_number": attempt_number}
        started = perf_counter()
        self._emit("step.started", **common)
        status, error_category = "completed", None
        try:
            yield current.workflow_id
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            error_category = type(exc).__name__
            raise
        finally:
            self._emit("step.finished", **common, status=status,
                       error_category=error_category,
                       duration_ms=(perf_counter() - started) * 1000)
            self._context.reset(token)

    def _decorate(self, name: str, workflow: bool):
        label(name, "name")
        def decorate(function):
            if inspect.isgeneratorfunction(function) or inspect.isasyncgenfunction(function):
                raise TypeError("Instrument generator consumption with an explicit span")
            if inspect.iscoroutinefunction(function):
                @wraps(function)
                async def wrapped(*args, **kwargs):
                    with self.span(name, workflow=workflow):
                        return await function(*args, **kwargs)
            else:
                @wraps(function)
                def wrapped(*args, **kwargs):
                    with self.span(name, workflow=workflow):
                        return function(*args, **kwargs)
            return wrapped
        return decorate

    def workflow(self, name: str):
        return self._decorate(name, True)

    def operation(self, name: str):
        return self._decorate(name, False)

    def record_usage(self, provider: str, service: str, units: dict[str, int | float], *,
                     amount: str | None = None, currency: str | None = None,
                     cost_basis: str | None = None, price_version: str | None = None):
        """Record one usage measurement. Unknown cost is absent, never zero."""
        if self._context.get() is None:
            raise RuntimeError("Usage must be recorded inside a workflow or operation")
        usage(provider, service, units, amount, currency, cost_basis, price_version)
        self._emit("usage.recorded", provider=provider, model_or_service=service,
                   usage_units=dict(units), amount=amount, currency=currency,
                   cost_basis=cost_basis, price_version=price_version)

    def record_outcome(self, outcome_type: str, value: bool | str | int | float, *,
                       workflow_id: str | None = None, evaluator_version: str | None = None):
        """An explicit workflow ID allows feedback after execution has finished."""
        label(outcome_type, "outcome_type")
        label(workflow_id, "workflow_id", nullable=True)
        label(evaluator_version, "evaluator_version", nullable=True)
        scalar(value)
        current = self._context.get()
        target = workflow_id or (current.workflow_id if current else None)
        if target is None:
            raise RuntimeError("Outcome requires a workflow_id or active span")
        json.dumps(value, allow_nan=False)
        self._emit("outcome.recorded", workflow_id=target,
                   step_id=current.step_id if current and current.workflow_id == target else None,
                   outcome_type=outcome_type, value=value, evaluator_version=evaluator_version)

    def close(self, timeout: float = 5.0) -> bool:
        """Stop accepting events and drain the queue. False means export is unfinished."""
        with self._lock:
            self._closed = True
        self._worker.join(timeout=max(0, timeout))
        return not self._worker.is_alive()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
