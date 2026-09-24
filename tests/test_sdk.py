import asyncio
import unittest
from threading import Event

from traceworth import TraceWorth


class SDKTests(unittest.TestCase):
    def test_nested_usage_and_late_outcome(self):
        events = []
        with TraceWorth("any-app", events.append) as client:
            with client.span("request", workflow=True) as workflow_id:
                with client.span("model"):
                    client.record_usage("example", "model", {"input_tokens": 10},
                                        amount="0.001", currency="USD", cost_basis="estimated")
            client.record_outcome("accepted", True, workflow_id=workflow_id)
        self.assertEqual(len(events), 6)
        root, child, usage = events[:3]
        self.assertEqual(child["parent_step_id"], root["step_id"])
        self.assertEqual(usage["step_id"], child["step_id"])
        self.assertEqual({e["workflow_id"] for e in events}, {workflow_id})
        self.assertIsNone(events[-1]["step_id"])

    def test_async_isolation_failure_and_cancellation(self):
        events = []
        with TraceWorth("app", events.append) as client:
            @client.operation("child")
            async def child():
                await asyncio.sleep(0)

            @client.workflow("root")
            async def run(kind):
                await child()
                if kind == "failure":
                    raise ValueError("sensitive error message")
                if kind == "cancel":
                    raise asyncio.CancelledError()
                return 42

            async def main():
                return await asyncio.gather(run("ok"), run("failure"), run("cancel"),
                                            return_exceptions=True)
            results = asyncio.run(main())
        self.assertEqual(results[0], 42)
        self.assertIsInstance(results[1], ValueError)
        roots = [e for e in events if e["name"] == "root" and e["event_type"] == "step.started"]
        self.assertEqual(len({e["workflow_id"] for e in roots}), 3)
        finishes = [e for e in events if e["name"] == "root" and e["event_type"] == "step.finished"]
        self.assertEqual({e["status"] for e in finishes}, {"completed", "failed", "cancelled"})
        self.assertNotIn("sensitive error message", str(events))
        for root in roots:
            children = [e for e in events if e["name"] == "child" and e["workflow_id"] == root["workflow_id"]]
            self.assertEqual(len(children), 2)
            self.assertTrue(all(e["parent_step_id"] == root["step_id"] for e in children))

    def test_export_failure_does_not_break_application(self):
        def broken(event):
            raise OSError("unavailable")
        with TraceWorth("app", broken) as client:
            @client.workflow("work")
            def run(secret):
                return secret
            self.assertEqual(run("private"), "private")
        self.assertEqual(client.diagnostics["export_errors"], 2)

    def test_overflow_and_shutdown_are_bounded(self):
        entered, release = Event(), Event()
        def slow(event):
            entered.set()
            release.wait(2)
        client = TraceWorth("app", slow, queue_size=1)
        try:
            with client.span("root"):
                self.assertTrue(entered.wait(1))
                for _ in range(5):
                    client.record_usage("p", "m", {"tokens": 1})
            self.assertGreater(client.diagnostics["dropped_events"], 0)
            self.assertFalse(client.close(timeout=0))
        finally:
            release.set()
            self.assertTrue(client.close())

    def test_validation_and_context_reset(self):
        events = []
        with TraceWorth("app", events.append) as client:
            with client.span("root"):
                with self.assertRaises(ValueError):
                    client.record_usage("p", "m", {"tokens": float("nan")})
                client.record_usage("p", "m", {"tokens": 3})
            with self.assertRaises(RuntimeError):
                client.record_usage("p", "m", {"tokens": 3})
        usage = next(e for e in events if e["event_type"] == "usage.recorded")
        self.assertIsNone(usage["amount"])


if __name__ == "__main__":
    unittest.main()
