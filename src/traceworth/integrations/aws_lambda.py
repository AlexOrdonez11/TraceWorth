"""Opt-in AWS Lambda handler wrapper with best-effort workflow telemetry.

Set the Lambda handler to ``traceworth.integrations.aws_lambda.handler`` and
``TRACEWORTH_ORIGINAL_HANDLER`` to the existing ``module.function`` handler.
The adapter never reads or exports the invocation event or handler result.
"""

from __future__ import annotations

import importlib
import logging
import math
import os
import sys
from typing import Any, Callable

from traceworth import HttpExporter, TraceWorth


_LOG = logging.getLogger(__name__)
_DEFAULT_EXPORT_TIMEOUT = 1.0
_LAMBDA_EXIT_MARGIN_MS = 100


def _original_handler() -> tuple[Callable[..., Any], str]:
    reference = os.environ.get("TRACEWORTH_ORIGINAL_HANDLER", "")
    module_name, separator, function_name = reference.rpartition(".")
    if not separator or not module_name or not function_name or not function_name.isidentifier():
        raise ValueError("TRACEWORTH_ORIGINAL_HANDLER must be module.function")
    try:
        original = getattr(importlib.import_module(module_name), function_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError("TRACEWORTH_ORIGINAL_HANDLER could not be resolved") from exc
    if original is handler or not callable(original):
        raise ValueError("TRACEWORTH_ORIGINAL_HANDLER must resolve to a different callable")
    return original, reference


def _telemetry_client() -> tuple[TraceWorth, float] | None:
    application = os.environ.get("TRACEWORTH_APPLICATION", "")
    endpoint = os.environ.get("TRACEWORTH_ENDPOINT", "")
    api_key = os.environ.get("TRACEWORTH_API_KEY", "")
    environment = os.environ.get("TRACEWORTH_ENVIRONMENT", "production")
    configuration_id = os.environ.get("TRACEWORTH_CONFIGURATION_ID") or None
    try:
        timeout = float(os.environ.get("TRACEWORTH_EXPORT_TIMEOUT", str(_DEFAULT_EXPORT_TIMEOUT)))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid timeout")
        exporter = HttpExporter(endpoint, api_key, timeout=timeout)
        client = TraceWorth(application, exporter, environment=environment,
                            configuration_id=configuration_id)
    except Exception:
        # Keep diagnostic text independent of configuration values and secrets.
        _LOG.warning("TraceWorth Lambda telemetry disabled: invalid configuration")
        return None
    return client, timeout


def _drain_timeout(context: Any, configured_timeout: float) -> float:
    try:
        remaining = getattr(context, "get_remaining_time_in_millis", None)
        if not callable(remaining):
            return configured_timeout
        milliseconds = remaining()
        if isinstance(milliseconds, bool) or not isinstance(milliseconds, (int, float)):
            return configured_timeout
        if not math.isfinite(milliseconds):
            return configured_timeout
        return min(configured_timeout, max(0.0, (milliseconds - _LAMBDA_EXIT_MARGIN_MS) / 1000.0))
    except Exception:
        return configured_timeout


def _close(client: TraceWorth, context: Any, timeout: float) -> None:
    try:
        drained = client.close(timeout=_drain_timeout(context, timeout))
        diagnostics = client.diagnostics
        if not drained or any(diagnostics.values()):
            _LOG.warning("TraceWorth Lambda telemetry incomplete: %d pending, %d dropped, %d export errors",
                         diagnostics["pending_events"], diagnostics["dropped_events"],
                         diagnostics["export_errors"])
    except Exception:
        _LOG.warning("TraceWorth Lambda telemetry could not finish")


def _preinstall_openai() -> bool:
    """Patch optional SDK methods before importing the application's module.

    Some clients cache bound raw-response methods during construction, so
    patching after importing their module can miss those calls.
    """
    setting = os.environ.get("TRACEWORTH_CAPTURE_OPENAI", "").strip().lower()
    if setting not in ("1", "true", "yes", "on"):
        if setting and setting not in ("0", "false", "no", "off"):
            _LOG.warning("TraceWorth OpenAI capture disabled: invalid setting")
        return False
    try:
        from .openai_sdk import install
        return install()
    except Exception:
        _LOG.warning("TraceWorth OpenAI capture could not start")
        return False


def _openai_capture(client: TraceWorth, installed: bool) -> Any | None:
    if not installed:
        return None
    try:
        from .openai_sdk import capture
        scope = capture(client)
        scope.__enter__()
        return scope
    except Exception:
        _LOG.warning("TraceWorth OpenAI capture could not start")
        return None


def handler(event: Any, context: Any) -> Any:
    """Call the original handler once and record a single root workflow span.

    Telemetry setup, span, and delivery failures do not change the original
    handler's result or exception. Export is best effort and is not durable.
    """
    openai_installed = _preinstall_openai()
    original, reference = _original_handler()
    configured = _telemetry_client()
    if configured is None:
        return original(event, context)

    client, timeout = configured
    try:
        scope = client.span(f"lambda:{reference}", workflow=True)
        scope.__enter__()
    except Exception:
        _LOG.warning("TraceWorth Lambda telemetry could not start")
        _close(client, context, timeout)
        return original(event, context)

    openai_scope = _openai_capture(client, openai_installed)
    try:
        return original(event, context)
    finally:
        exception = sys.exc_info()
        if openai_scope is not None:
            try:
                openai_scope.__exit__(*exception)
            except Exception:
                _LOG.warning("TraceWorth OpenAI capture could not finish")
        try:
            scope.__exit__(*exception)
        except Exception:
            _LOG.warning("TraceWorth Lambda telemetry could not finish the workflow")
        _close(client, context, timeout)
