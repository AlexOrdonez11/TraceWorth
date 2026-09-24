import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from traceworth.assessment import assess_events, assess_file


def event(event_type, *, workflow='workflow-1', step=None, **fields):
    item = dict(schema_version=1, event_id=str(uuid4()), event_type=event_type,
                occurred_at='2026-09-16T12:00:00+00:00', application_id='portable',
                environment='test', configuration_id='v1', workflow_id=workflow,
                step_id=step)
    item.update(fields)
    return item


def span(*, workflow='workflow-1', parent=None, duration=100, status='completed'):
    step = str(uuid4())
    fields = dict(workflow=workflow, step=step, name='root' if parent is None else 'child',
                  kind='workflow' if parent is None else 'operation', parent_step_id=parent,
                  attempt_number=1)
    return [event('step.started', **fields),
            event('step.finished', **fields, status=status, duration_ms=duration,
                  error_category='ValueError' if status == 'failed' else None)]


def usage(step, amount='0.1', *, workflow='workflow-1', currency='USD', basis='estimated'):
    return event('usage.recorded', workflow=workflow, step=step, provider='vendor',
                 model_or_service='model', usage_units={'tokens': 3}, amount=amount,
                 currency=currency if amount is not None else None,
                 cost_basis=basis if amount is not None else None, price_version=None)


def outcome(value, *, workflow='workflow-1', timestamp='2026-09-16T12:01:00+00:00'):
    return event('outcome.recorded', workflow=workflow, outcome_type='accepted', value=value,
                 evaluator_version=None, occurred_at=timestamp)


class AssessmentAcceptanceTests(unittest.TestCase):
    def test_decimal_costs_distinct_currencies_bases_and_unknown(self):
        events = span()
        step = events[0]['step_id']
        events += [usage(step, '0.1'), usage(step, '0.2'), usage(step, '0.4', currency='EUR'),
                   usage(step, '0.5', basis='provider_reported'), usage(step, None), outcome(True)]
        report = assess_events(events)
        cohort = report['cohorts'][0]
        costs = {(c['currency'], c['cost_basis']): c for c in cohort['costs']}
        self.assertEqual(costs['USD', 'estimated']['amount'], '0.3')
        self.assertEqual(costs['USD', 'estimated']['cost_per_accepted_result'], '0.3')
        self.assertEqual(costs['EUR', 'estimated']['amount'], '0.4')
        self.assertEqual(costs['USD', 'provider_reported']['amount'], '0.5')
        self.assertTrue(all(c['partial'] for c in costs.values()))
        self.assertEqual(cohort['summary']['unknown_cost_events'], 1)
        self.assertEqual(cohort['summary']['known_cost_events'], 4)

    def test_out_of_order_dedup_and_root_duration(self):
        root = span(duration=100)
        child = span(parent=root[0]['step_id'], duration=80)
        measurement = usage(child[0]['step_id'])
        report = assess_events([child[1], root[1], measurement, root[0], child[0], copy.deepcopy(measurement)])
        self.assertEqual(report['input']['duplicate_events'], 1)
        cohort = report['cohorts'][0]
        self.assertEqual(cohort['workflows'][0]['duration_ms'], 100)
        self.assertEqual(cohort['summary']['steps'], 2)
        self.assertEqual(cohort['costs'][0]['amount'], '0.1')

    def test_latest_feedback_wins_and_zero_accepted_is_undefined(self):
        events = span()
        events += [usage(events[0]['step_id']), outcome(False),
                   outcome(True, timestamp='2026-09-16T12:00:30+00:00')]
        cohort = assess_events(events)['cohorts'][0]
        self.assertEqual(cohort['summary']['accepted_workflows'], 0)
        self.assertFalse(cohort['workflows'][0]['accepted'])
        self.assertIsNone(cohort['costs'][0]['cost_per_accepted_result'])

    def test_failed_workflow_cost_included_in_accepted_denominator(self):
        first = span(workflow='good')
        second = span(workflow='failed', status='failed')
        events = first + second + [usage(first[0]['step_id'], '1', workflow='good'),
                                  usage(second[0]['step_id'], '2', workflow='failed'),
                                  outcome(True, workflow='good')]
        cohort = assess_events(events)['cohorts'][0]
        self.assertEqual(cohort['costs'][0]['cost_per_accepted_result'], '3')
        self.assertEqual(cohort['summary']['failed_steps'], 1)

    def test_missing_start_and_finish_are_disclosed(self):
        root = span()
        other = span(workflow='orphan', parent=str(uuid4()))
        cohort = assess_events([root[0], other[1]])['cohorts'][0]
        self.assertEqual(cohort['summary']['incomplete_steps'], 2)
        self.assertEqual(cohort['summary']['orphan_steps'], 1)
        self.assertTrue(cohort['findings'])

    def test_incomplete_trace_cost_is_partial_and_step_cost_attributed(self):
        root = span()
        events = [root[0], usage(root[0]['step_id'], '2')]
        cohort = assess_events(events)['cohorts'][0]
        self.assertTrue(cohort['costs'][0]['partial'])
        step = cohort['workflows'][0]['steps'][0]
        self.assertEqual(step['usage_events'], 1)
        self.assertEqual(step['costs'][0]['amount'], '2')
        self.assertEqual(step['unknown_cost_events'], 0)

    def test_cost_finding_points_to_expensive_step_without_parent_rollup(self):
        root = span()
        child = span(parent=root[0]['step_id'])
        cohort = assess_events(root + child + [usage(root[0]['step_id'], '1'),
                                               usage(child[0]['step_id'], '2')])['cohorts'][0]
        steps = {step['step_id']: step for step in cohort['workflows'][0]['steps']}
        self.assertEqual(steps[root[0]['step_id']]['costs'][0]['amount'], '1')
        self.assertEqual(steps[child[0]['step_id']]['costs'][0]['amount'], '2')
        self.assertEqual(cohort['costs'][0]['amount'], '3')
        finding = next(f for f in cohort['findings'] if f['code'] == 'highest_recorded_step_cost')
        self.assertEqual(finding['evidence'], [child[0]['step_id']])
        self.assertEqual(finding['amount'], '2')
        self.assertEqual(finding['currency'], 'USD')

    def test_invalid_input_discloses_partial_cost_and_report_time_bounds(self):
        root = span()
        cohort = assess_events(root + [usage(root[0]['step_id']), outcome(True), {}])['cohorts'][0]
        self.assertTrue(cohort['costs'][0]['partial'])
        self.assertEqual(cohort['summary']['completed_workflows'], 1)
        self.assertEqual(cohort['summary']['failed_workflows'], 0)
        self.assertEqual(cohort['summary']['cancelled_workflows'], 0)
        self.assertEqual(cohort['observed_time_range']['start'], '2026-09-16T12:00:00+00:00')
        self.assertEqual(cohort['observed_time_range']['end'], '2026-09-16T12:01:00+00:00')
        self.assertEqual(cohort['acceptance_cutoff_at'], cohort['observed_time_range']['end'])

    def test_conflicting_replay_retains_first_cost_with_diagnostic(self):
        events = span()
        original = usage(events[0]['step_id'], '1')
        conflicting = dict(original, amount='999')
        report = assess_events(events + [original, conflicting])
        self.assertEqual(report['cohorts'][0]['costs'][0]['amount'], '1')
        self.assertEqual(report['input']['duplicate_events'], 1)
        self.assertTrue(report['input']['errors'])

    def test_large_and_tiny_amounts_sum_without_decimal_rounding(self):
        events = span()
        step = events[0]['step_id']
        large = '123456789012345678901234567890.123456789'
        events += [usage(step, large), usage(step, '0.000000001')]
        amount = assess_events(events)['cohorts'][0]['costs'][0]['amount']
        self.assertEqual(amount, '123456789012345678901234567890.123456790')

    def test_zero_price_is_known_and_nonboolean_acceptance_is_not_accepted(self):
        events = span()
        events += [usage(events[0]['step_id'], '0'), outcome('true')]
        cohort = assess_events(events)['cohorts'][0]
        self.assertEqual(cohort['summary']['known_cost_events'], 1)
        self.assertEqual(cohort['summary']['accepted_workflows'], 0)
        self.assertIsNone(cohort['workflows'][0]['accepted'])
        self.assertFalse(cohort['costs'][0]['partial'])

    def test_timezone_offsets_order_feedback_by_instant(self):
        events = span() + [outcome(True, timestamp='2026-09-16T13:00:00+02:00'),
                           outcome(False, timestamp='2026-09-16T12:00:00+00:00')]
        self.assertFalse(assess_events(events)['cohorts'][0]['workflows'][0]['accepted'])

    def test_lowercase_rfc3339_timestamp_can_be_assessed(self):
        events = span() + [outcome(True, timestamp='2026-09-16t12:01:00z')]
        report = assess_events(events)
        self.assertEqual(report['input']['invalid_lines'], 0)
        self.assertTrue(report['cohorts'][0]['workflows'][0]['accepted'])

    def test_malformed_field_types_do_not_abort_assessment(self):
        templates = span()
        templates += [usage(templates[0]['step_id']), outcome(True)]
        mutated = []
        for template in templates:
            for key in template:
                for bad in [[], {}, None, True, 17]:
                    mutated.append(dict(template, **{key: bad}))
        report = assess_events(mutated)
        self.assertGreater(report['input']['invalid_lines'], 100)

    def test_application_environment_configuration_are_independent_cohorts(self):
        base = span()
        events = []
        for field, value in [(None, None), ('application_id', 'second'),
                             ('environment', 'prod'), ('configuration_id', 'v2')]:
            for original in base:
                item = dict(original, event_id=str(uuid4()))
                if field:
                    item[field] = value
                events.append(item)
        report = assess_events(events)
        self.assertEqual(len(report['cohorts']), 4)
        self.assertTrue(all(c['summary']['workflows'] == 1 for c in report['cohorts']))

    def test_deeply_nested_file_record_isolated_without_losing_valid_events(self):
        good = span()
        nested = '[' * 1500 + '0' + ']' * 1500
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.jsonl'
            path.write_text(json.dumps(good[0]) + '\n' + nested + '\n' + json.dumps(good[1]) + '\n', encoding='utf-8')
            report = assess_file(path)
        self.assertEqual(report['input']['invalid_lines'], 1)
        self.assertEqual(report['input']['valid_events'], 2)
        self.assertEqual(report['input']['errors'][0]['line'], 2)
        self.assertEqual(report['cohorts'][0]['summary']['workflows'], 1)

    def test_malformed_lines_isolated_and_valid_lines_retained(self):
        good = span()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.jsonl'
            path.write_text(json.dumps(good[0]) + '\n{bad json\n[]\n' + json.dumps(good[1]) + '\n', encoding='utf-8')
            report = assess_file(path)
        self.assertEqual(report['input']['invalid_lines'], 2)
        self.assertEqual(report['input']['valid_events'], 2)
        self.assertEqual({e['line'] for e in report['input']['errors']}, {2, 3})
        self.assertEqual(report['cohorts'][0]['summary']['workflows'], 1)


class CLIAcceptanceTests(unittest.TestCase):
    def run_cli(self, *args):
        environment = dict(os.environ)
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        return subprocess.run([sys.executable, '-m', 'traceworth', *map(str, args)],
                              text=True, capture_output=True, env=environment, timeout=30)

    def test_demo_and_assess_reproducible_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            events = Path(temporary) / 'demo.jsonl'
            demo = self.run_cli('demo', '--output', events)
            self.assertEqual(demo.returncode, 0, demo.stderr)
            self.assertTrue(events.is_file())
            assessment = self.run_cli('assess', events, '--format', 'json')
            self.assertEqual(assessment.returncode, 0, assessment.stderr)
            report = json.loads(assessment.stdout)
            self.assertEqual(report['input']['invalid_lines'], 0)
            self.assertGreaterEqual(len(report['cohorts']), 3)
            destination = Path(temporary) / 'report.txt'
            rendered = self.run_cli('assess', events, '--format', 'text', '--output', destination)
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            self.assertGreater(len(destination.read_text(encoding='utf-8')), 100)

    def test_demo_and_assessment_preserve_input_on_path_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            events = Path(temporary) / 'events.jsonl'
            events.write_text('existing telemetry\n', encoding='utf-8')
            original = events.read_bytes()
            demo = self.run_cli('demo', '--output', events)
            self.assertEqual(demo.returncode, 2)
            self.assertEqual(events.read_bytes(), original)
            assessment = self.run_cli('assess', events, '--output', events)
            self.assertEqual(assessment.returncode, 2)
            self.assertEqual(events.read_bytes(), original)

    def test_missing_input_is_actionable_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_cli('assess', Path(temporary) / 'missing.jsonl')
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.strip())
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()

