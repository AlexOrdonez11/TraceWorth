"""Opt-in, response-only capture for direct OpenAI Python SDK create calls.

The class methods are wrapped once per process. A ContextVar makes the wrappers
pass through unless a TraceWorth client is active for the current execution.
Only the request's streaming flag, response model, and provider-reported token
counts are read; prompts, generated text, and credentials are never inspected.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from importlib.metadata import version
import logging
import sys
from threading import Lock
from typing import Any, Iterator

from traceworth import TraceWorth


_LOG = logging.getLogger(__name__)
_ACTIVE: ContextVar[TraceWorth | None] = ContextVar("traceworth_openai_client", default=None)
_INSTALL_LOCK = Lock()
_INSTALLED = False
_SUPPORTED_OPENAI_MINORS = {("2", "54"), ("3", "19")}


def _token_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _record_response(client: TraceWorth, response: Any, kind: str) -> None:
    model = getattr(response, "model", None)
    usage = getattr(response, "usage", None)
    if not isinstance(model, str) or not model.strip() or usage is None:
        return
    if kind == "responses":
        input_count = _token_count(getattr(usage, "input_tokens", None))
        output_count = _token_count(getattr(usage, "output_tokens", None))
    else:
        input_count = _token_count(getattr(usage, "prompt_tokens", None))
        output_count = _token_count(getattr(usage, "completion_tokens", None))
    units = {}
    if input_count is not None:
        units["input_tokens"] = input_count
    if output_count is not None:
        units["output_tokens"] = output_count
    if units:
        client.record_usage("openai", model, units)


def _safe_exit(scope: Any, *exception: Any) -> None:
    try:
        scope.__exit__(*exception)
    except Exception:
        _LOG.warning("TraceWorth OpenAI telemetry could not finish the operation")


def _sync_wrapper(method: Any, kind: str):
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        client = _ACTIVE.get()
        if client is None or kwargs.get("stream") is True:
            return method(self, *args, **kwargs)
        try:
            scope = client.span(f"openai.{kind}.create")
            scope.__enter__()
        except Exception:
            _LOG.warning("TraceWorth OpenAI telemetry could not start")
            return method(self, *args, **kwargs)
        try:
            response = method(self, *args, **kwargs)
        except BaseException:
            _safe_exit(scope, *sys.exc_info())
            raise
        try:
            _record_response(client, response, kind)
        except Exception:
            _LOG.warning("TraceWorth OpenAI telemetry could not read usage")
        _safe_exit(scope, None, None, None)
        return response
    return wrapped


def _async_wrapper(method: Any, kind: str):
    @wraps(method)
    async def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        client = _ACTIVE.get()
        if client is None or kwargs.get("stream") is True:
            return await method(self, *args, **kwargs)
        try:
            scope = client.span(f"openai.{kind}.create")
            scope.__enter__()
        except Exception:
            _LOG.warning("TraceWorth OpenAI telemetry could not start")
            return await method(self, *args, **kwargs)
        try:
            response = await method(self, *args, **kwargs)
        except BaseException:
            _safe_exit(scope, *sys.exc_info())
            raise
        try:
            _record_response(client, response, kind)
        except Exception:
            _LOG.warning("TraceWorth OpenAI telemetry could not read usage")
        _safe_exit(scope, None, None, None)
        return response
    return wrapped


def install() -> bool:
    """Install passive wrappers for direct Responses and Chat Completions calls.

    Returns False if the optional OpenAI package or required methods are absent.
    Existing OpenAI objects receive the class method wrapper too. Installation
    is process-wide, idempotent, and passive outside ``capture``.
    """
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return True
        try:
            if tuple(version("openai").split(".")[:2]) not in _SUPPORTED_OPENAI_MINORS:
                raise ValueError("unsupported OpenAI SDK version")
            from openai.resources.responses import Responses, AsyncResponses
            from openai.resources.chat.completions import Completions, AsyncCompletions
            targets = (
                (Responses, "responses", _sync_wrapper),
                (AsyncResponses, "responses", _async_wrapper),
                (Completions, "chat.completions", _sync_wrapper),
                (AsyncCompletions, "chat.completions", _async_wrapper),
            )
            if any(not callable(getattr(cls, "create", None)) for cls, _, _ in targets):
                raise TypeError("OpenAI create method unavailable")
        except Exception:
            _LOG.warning("TraceWorth OpenAI capture disabled: compatible SDK methods unavailable")
            return False
        original = [(cls, cls.create) for cls, _, _ in targets]
        try:
            for cls, kind, factory in targets:
                cls.create = factory(cls.create, kind)
        except Exception:
            for cls, method in original:
                cls.create = method
            _LOG.warning("TraceWorth OpenAI capture disabled: SDK methods could not be wrapped")
            return False
        _INSTALLED = True
        return True


@contextmanager
def capture(client: TraceWorth) -> Iterator[None]:
    """Associate direct OpenAI create calls in this execution with ``client``."""
    token = _ACTIVE.set(client)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
