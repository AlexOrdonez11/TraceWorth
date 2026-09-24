"""Version 1 event validation shared by producers and local report readers."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
import re
from uuid import UUID


BASE = {"schema_version", "event_id", "event_type", "occurred_at", "application_id",
        "environment", "configuration_id", "workflow_id", "step_id"}
STEP = {"name", "kind", "parent_step_id", "attempt_number"}
FIELDS = {
    "step.started": STEP,
    "step.finished": STEP | {"status", "error_category", "duration_ms"},
    "usage.recorded": {"provider", "model_or_service", "usage_units", "amount",
                       "currency", "cost_basis", "price_version"},
    "outcome.recorded": {"outcome_type", "value", "evaluator_version"},
}
COST_BASES = {"provider_reported", "estimated", "allocated"}


def label(value, field, *, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")


def positive_integer(value, field):
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def nonnegative_number(value, field):
    if type(value) not in (int, float) or value < 0:
        raise ValueError(f"{field} must be finite and nonnegative")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be finite and nonnegative")


def scalar(value):
    if type(value) not in (bool, str, int, float):
        raise ValueError("outcome value must be a boolean, string, integer, or finite float")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("outcome value must be finite")


def usage(provider, service, units, amount, currency, cost_basis, price_version):
    label(provider, "provider")
    label(service, "model_or_service")
    if not isinstance(units, dict) or not units:
        raise ValueError("usage_units must be a nonempty mapping")
    for key, value in units.items():
        label(key, "usage unit key")
        nonnegative_number(value, key)
    label(price_version, "price_version", nullable=True)
    if amount is None:
        if any(value is not None for value in (currency, cost_basis, price_version)):
            raise ValueError("Unknown cost must have null currency, cost_basis, and price_version")
        return
    if not isinstance(amount, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", amount):
        raise ValueError("amount must be a nonnegative plain decimal string")
    try:
        number = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal amount") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("amount must be finite and nonnegative")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be a three-letter uppercase code")
    if not isinstance(cost_basis, str) or cost_basis not in COST_BASES:
        raise ValueError("Unsupported cost_basis")


def _identifier(value, field, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UUID string")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID string") from exc
    if str(parsed) != value.lower():
        raise ValueError(f"{field} must be a hyphenated UUID string")


def validate_event(event):
    """Raise ValueError for unsupported, malformed, or inconsistent envelopes.

    Additive fields are accepted for forward-compatible version 1 producers.
    Validation does not establish authentic ownership or complete capture.
    """
    if not isinstance(event, dict):
        raise ValueError("Event must be an object")
    if type(event.get("schema_version")) is not int or event["schema_version"] != 1:
        raise ValueError("Unsupported schema_version")
    kind = event.get("event_type")
    if not isinstance(kind, str) or kind not in FIELDS:
        raise ValueError("Unsupported event_type")
    missing = (BASE | FIELDS[kind]) - event.keys()
    if missing:
        raise ValueError(f"Missing fields: {', '.join(sorted(missing))}")
    _identifier(event["event_id"], "event_id")
    _identifier(event["step_id"], "step_id", nullable=kind == "outcome.recorded")
    for name in ("application_id", "environment", "workflow_id"):
        label(event[name], name)
    label(event["configuration_id"], "configuration_id", nullable=True)
    try:
        if not isinstance(event["occurred_at"], str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
                event["occurred_at"]):
            raise ValueError("Timestamp must use RFC3339 syntax")
        stamp = datetime.fromisoformat(event["occurred_at"].upper().replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            raise ValueError("Timestamp requires a timezone")
    except (TypeError, AttributeError, ValueError) as exc:
        raise ValueError("occurred_at must be a timezone-aware ISO timestamp") from exc
    if kind.startswith("step."):
        label(event["name"], "name")
        if event["kind"] not in ("workflow", "operation"):
            raise ValueError("Unsupported step kind")
        _identifier(event["parent_step_id"], "parent_step_id", nullable=True)
        positive_integer(event["attempt_number"], "attempt_number")
        if event["kind"] == "workflow" and event["parent_step_id"] is not None:
            raise ValueError("Workflow roots cannot have a parent_step_id")
    if kind == "step.finished":
        if event["status"] not in ("completed", "failed", "cancelled"):
            raise ValueError("Unsupported status")
        label(event["error_category"], "error_category", nullable=True)
        nonnegative_number(event["duration_ms"], "duration_ms")
        if event["status"] == "completed" and event["error_category"] is not None:
            raise ValueError("Completed steps cannot have an error_category")
    if kind == "usage.recorded":
        usage(event["provider"], event["model_or_service"], event["usage_units"],
              event["amount"], event["currency"], event["cost_basis"], event["price_version"])
    if kind == "outcome.recorded":
        label(event["outcome_type"], "outcome_type")
        label(event["evaluator_version"], "evaluator_version", nullable=True)
        scalar(event["value"])
