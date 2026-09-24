import copy
import unittest

from traceworth import TraceWorth
from traceworth.validation import validate_event


class ValidationAcceptanceTests(unittest.TestCase):
    def capture(self):
        events = []
        with TraceWorth('portable-app', events.append) as sdk:
            with sdk.span('workflow', workflow=True):
                sdk.record_usage('vendor', 'service', {'tokens': 5}, amount='0.10',
                                 currency='USD', cost_basis='estimated')
                sdk.record_outcome('accepted', True)
        return events

    def test_all_sdk_event_types_validate(self):
        events = self.capture()
        self.assertEqual({e['event_type'] for e in events},
                         {'step.started', 'step.finished', 'usage.recorded', 'outcome.recorded'})
        for event in events:
            validate_event(event)

    def test_invalid_envelopes_rejected(self):
        template = self.capture()[0]
        for key, value in [('schema_version', True), ('schema_version', 2),
                           ('event_id', 'not-a-uuid'), ('application_id', ''),
                           ('environment', ' '), ('configuration_id', ''),
                           ('workflow_id', ''), ('step_id', None),
                           ('occurred_at', '2026-09-16T12:00:00'),
                           ('attempt_number', True), ('attempt_number', 0)]:
            with self.subTest(key=key, value=value):
                event = copy.deepcopy(template)
                event[key] = value
                with self.assertRaises(ValueError):
                    validate_event(event)

    def test_invalid_usage_and_outcomes_rejected(self):
        events = self.capture()
        usage = next(e for e in events if e['event_type'] == 'usage.recorded')
        for changes in [{'amount': float('nan')}, {'amount': '-1'},
                        {'currency': 'usd'}, {'cost_basis': None},
                        {'usage_units': {'tokens': True}}, {'usage_units': {'tokens': -1}},
                        {'usage_units': {'tokens': float('inf')}}, {'provider': ''}]:
            with self.subTest(changes=changes):
                event = dict(usage, **changes)
                with self.assertRaises(ValueError):
                    validate_event(event)
        outcome = next(e for e in events if e['event_type'] == 'outcome.recorded')
        for value in [None, [], {}, float('nan'), float('inf')]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_event(dict(outcome, value=value))

    def test_rfc3339_timestamp_case_and_offset_limits(self):
        template = self.capture()[0]
        validate_event(dict(template, occurred_at='2026-09-16t12:00:00z'))
        for timestamp in ['2026-09-16T12:00:00+24:00', '2026-09-16T12:00:00+01:60',
                          '2026-09-16 12:00:00+00:00', '20260916T120000+0000']:
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(ValueError):
                    validate_event(dict(template, occurred_at=timestamp))

    def test_bad_recording_does_not_corrupt_context(self):
        events = []
        with TraceWorth('app', events.append) as sdk:
            with sdk.span('root', workflow=True) as workflow_id:
                for action in [lambda: sdk.record_usage('p', 'm', {'tokens': True}),
                               lambda: sdk.record_outcome('accepted', {}),
                               lambda: sdk.record_usage('p', 'm', {}, amount='oops', currency='USD', cost_basis='estimated')]:
                    with self.assertRaises(ValueError):
                        action()
                with self.assertRaises(ValueError):
                    with sdk.span('', attempt_number=0):
                        pass
                sdk.record_usage('p', 'm', {'tokens': 1})
        for event in events:
            validate_event(event)
            self.assertEqual(event['workflow_id'], workflow_id)
        self.assertEqual(len(events), 3)


if __name__ == '__main__':
    unittest.main()
