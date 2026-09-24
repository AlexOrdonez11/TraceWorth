"""Validate checked-in examples against both published and runtime contracts."""
import copy
import json
from pathlib import Path
import unittest

from traceworth.validation import validate_event

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    Draft202012Validator = None


ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    def test_fixtures_runtime_validation(self):
        events = json.loads((ROOT / "tests/fixtures/events-v1.json").read_text())
        self.assertEqual({e["event_type"] for e in events},
                         {"step.started", "step.finished", "usage.recorded", "outcome.recorded"})
        for event in events:
            validate_event(event)

    @unittest.skipIf(Draft202012Validator is None, 'Install .[test] for formal schema verification')
    def test_json_schema_matches_valid_and_invalid_examples(self):
        schema = json.loads((ROOT / "schemas/event-v1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        events = json.loads((ROOT / "tests/fixtures/events-v1.json").read_text())
        for event in events:
            validator.validate(event)
        cases = [
            (events[0], "attempt_number", 0),
            (events[0], "name", "  "),
            (events[0], "step_id", None),
            (events[0], "occurred_at", "2026-09-16T00:00:00"),
            (events[2], "currency", "usd"),
            (events[2], "amount", "-0.1"),
            (events[2], "amount", None),
            (events[-1], "value", {"private": "content"}),
        ]
        for base, field, value in cases:
            with self.subTest(field=field, value=value):
                invalid = copy.deepcopy(base)
                invalid[field] = value
                self.assertFalse(validator.is_valid(invalid))
                with self.assertRaises(ValueError):
                    validate_event(invalid)
