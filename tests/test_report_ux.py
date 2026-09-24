"""User-facing report regressions, independent of presentation implementation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from traceworth.assessment import assess_events, format_text
from test_mvp_acceptance import span, usage, outcome


def run_cli(*args):
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    return subprocess.run([sys.executable, '-m', 'traceworth', *map(str, args)],
                          capture_output=True, text=True, timeout=15, env=environment)


class ReportUXTests(unittest.TestCase):
    def test_steps_follow_tree_then_chronological_siblings(self):
        root = span()
        earlier = span(parent=root[0]['step_id'])
        later = span(parent=root[0]['step_id'])
        grandchild = span(parent=earlier[0]['step_id'])
        for pair, stamp, name in [(root, '00', 'root'), (earlier, '01', 'earlier'),
                                   (later, '02', 'later'), (grandchild, '03', 'grandchild')]:
            for item in pair:
                item['occurred_at'] = '2026-09-16T12:00:' + stamp + '+00:00'
                item['name'] = name
        report = assess_events(later + grandchild + earlier + root)
        steps = report['cohorts'][0]['workflows'][0]['steps']
        self.assertEqual([s['name'] for s in steps], ['root', 'earlier', 'grandchild', 'later'])
        self.assertEqual([s['depth'] for s in steps], [0, 1, 2, 1])
        self.assertEqual(steps[0]['started_at'], '2026-09-16T12:00:00+00:00')
        self.assertTrue(all(not s['cycle'] for s in steps))

    def test_orphans_and_cycles_remain_visible(self):
        orphan = span(parent=str(uuid4()))
        first = span(parent=str(uuid4()))
        second = span(parent=first[0]['step_id'])
        for item in first:
            item['parent_step_id'] = second[0]['step_id']
        report = assess_events(orphan + first + second)
        steps = report['cohorts'][0]['workflows'][0]['steps']
        self.assertEqual(len(steps), 3)
        self.assertEqual(len({s['step_id'] for s in steps}), 3)
        self.assertTrue(any(s['orphan'] for s in steps))
        self.assertTrue(any(s['cycle'] for s in steps))
        self.assertTrue(format_text(report, detail=True))

    def test_default_summary_shows_usage_and_detail_keeps_evidence(self):
        root = span()
        measurement = usage(root[0]['step_id'], '1')
        measurement['usage_units'] = {'input_tokens': 11, 'output_tokens': 7}
        report = assess_events(root + [measurement, outcome(True)])
        summary = format_text(report)
        self.assertIn('vendor', summary)
        self.assertIn('model', summary)
        self.assertIn('input_tokens', summary)
        self.assertIn('11', summary)
        self.assertIn('output_tokens', summary)
        self.assertNotIn(root[0]['step_id'], summary)
        detail = format_text(report, detail=True)
        self.assertIn(root[0]['step_id'], detail)
        self.assertIn('workflow-1', detail)
        self.assertGreater(len(detail), len(summary))

    def test_empty_and_invalid_only_input_explains_next_action(self):
        for events in [[], [{}]]:
            with self.subTest(events=events):
                rendered = format_text(assess_events(events)).lower()
                self.assertIn('no', rendered)
                self.assertTrue(any(word in rendered for word in ['valid', 'usable', 'data']))
                self.assertTrue(any(word in rendered for word in ['demo', 'instrument', 'capture', 'record']))

    def test_cli_detail_help_and_saved_confirmation(self):
        help_result = run_cli('assess', '--help')
        self.assertEqual(help_result.returncode, 0)
        self.assertIn('--detail', help_result.stdout)
        main_help = run_cli('--help')
        self.assertIn('serve', main_help.stdout)
        with tempfile.TemporaryDirectory() as temporary:
            events = Path(temporary) / 'events.jsonl'
            records = span()
            events.write_text(''.join(json.dumps(e) + '\n' for e in records), encoding='utf-8')
            plain = run_cli('assess', events)
            detail = run_cli('assess', events, '--detail')
            self.assertEqual(detail.returncode, 0, detail.stderr)
            self.assertNotIn(records[0]['step_id'], plain.stdout)
            self.assertIn(records[0]['step_id'], detail.stdout)
            output = Path(temporary) / 'assessment.json'
            saved = run_cli('assess', events, '--format', 'json', '--output', output)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertEqual(saved.stdout, '')
            self.assertIn(str(output), saved.stderr)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['input']['valid_events'], 2)


if __name__ == '__main__':
    unittest.main()
