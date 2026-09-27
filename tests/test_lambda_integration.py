"""Independent acceptance checks for the opt-in AWS Lambda handler wrapper."""

import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
import json
import os
import sys
from threading import Thread
import time
from types import ModuleType
import unittest
from unittest.mock import patch

from openai import AsyncOpenAI, AuthenticationError, OpenAI

if version("openai").split(".", 1)[0] == "2":
    import httpx as provider_http
else:
    import httpx2 as provider_http

from traceworth.integrations.aws_lambda import handler


@contextmanager
def ingestion_receiver(*, status=200, delay=0):
    requests = []

    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append({"path": self.path, "headers": dict(self.headers),
                             "body": json.loads(body)})
            if delay:
                time.sleep(delay)
            payload = json.dumps({"accepted": 1, "duplicates": 0}).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/events", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class FakeContext:
    def __init__(self, remaining_ms=30_000):
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self):
        return self.remaining_ms


class LambdaIntegrationTests(unittest.TestCase):
    module_name = "traceworth_test_lambda_target"

    @contextmanager
    def target(self, function):
        module = ModuleType(self.module_name)
        module.handle = function
        module.not_callable = 42
        with patch.dict(sys.modules, {self.module_name: module}):
            yield module

    @contextmanager
    def config(self, endpoint=None, **overrides):
        values = {"TRACEWORTH_ORIGINAL_HANDLER": f"{self.module_name}.handle"}
        if endpoint is not None:
            values.update({"TRACEWORTH_APPLICATION": "test-app",
                           "TRACEWORTH_ENDPOINT": endpoint,
                           "TRACEWORTH_API_KEY": "test-ingestion-key"})
        values.update(overrides)
        with patch.dict(os.environ, values, clear=True):
            yield

    def test_success_preserves_result_and_captures_only_workflow_metadata(self):
        secret = "sensitive-user-prompt-729"
        context = FakeContext()

        def original(event, supplied_context):
            self.assertIs(supplied_context, context)
            return {"result": event["prompt"], "access_token": "private-response-918"}

        with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(endpoint):
            result = handler({"prompt": secret, "api_key": "private-input-456"}, context)

        self.assertEqual(result, {"result": secret, "access_token": "private-response-918"})
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(item["path"] == "/api/events" for item in requests))
        self.assertTrue(all(item["headers"]["Authorization"] == "Bearer test-ingestion-key"
                            for item in requests))
        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual([event["event_type"] for event in events],
                         ["step.started", "step.finished"])
        self.assertEqual({event["kind"] for event in events}, {"workflow"})
        self.assertEqual({event["application_id"] for event in events}, {"test-app"})
        self.assertEqual({event["environment"] for event in events}, {"production"})
        self.assertEqual(events[0]["workflow_id"], events[1]["workflow_id"])
        self.assertEqual(events[1]["status"], "completed")
        serialized_events = json.dumps(events)
        for private_value in (secret, "private-input-456", "private-response-918",
                              "test-ingestion-key"):
            self.assertNotIn(private_value, serialized_events)

    def test_business_exception_propagates_unchanged_without_message_capture(self):
        failure = ValueError("private-exception-message-314")

        def original(event, context):
            raise failure

        with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(endpoint):
            with self.assertRaises(ValueError) as caught:
                handler({"secret": "private-input-512"}, FakeContext())

        self.assertIs(caught.exception, failure)
        self.assertEqual(len(requests), 2)
        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(events[-1]["status"], "failed")
        self.assertEqual(events[-1]["error_category"], "ValueError")
        self.assertNotIn(str(failure), json.dumps(events))
        self.assertNotIn("private-input-512", json.dumps(events))

    def test_warm_repeated_invocations_have_separate_workflows_and_drain(self):
        def original(event, context):
            return event["number"] * 2

        with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(endpoint):
            self.assertEqual(handler({"number": 3}, FakeContext()), 6)
            self.assertEqual(len(requests), 2, "first invocation should flush before return")
            self.assertEqual(handler({"number": 5}, FakeContext()), 10)

        self.assertEqual(len(requests), 4)
        events = [item["body"]["events"][0] for item in requests]
        starts = [event for event in events if event["event_type"] == "step.started"]
        self.assertEqual(len(starts), 2)
        self.assertNotEqual(starts[0]["workflow_id"], starts[1]["workflow_id"])
        self.assertEqual(len({event["event_id"] for event in events}), 4)

    def test_missing_or_invalid_telemetry_config_fails_open(self):
        calls = []

        def original(event, context):
            calls.append(event)
            return "business-result"

        with self.target(original):
            for extra in ({}, {"TRACEWORTH_APPLICATION": "test-app"},
                          {"TRACEWORTH_APPLICATION": "test-app",
                           "TRACEWORTH_ENDPOINT": "http://example.com/api/events",
                           "TRACEWORTH_API_KEY": "test-key"},
                          {"TRACEWORTH_APPLICATION": "test-app",
                           "TRACEWORTH_ENDPOINT": "http://localhost/api/events",
                           "TRACEWORTH_API_KEY": "test-key",
                           "TRACEWORTH_EXPORT_TIMEOUT": "0"}):
                with self.subTest(extra=extra), self.config(**extra):
                    self.assertEqual(handler({"private": "value"}, FakeContext()),
                                     "business-result")
        self.assertEqual(len(calls), 4)

    def test_export_http_failure_does_not_change_business_result(self):
        def original(event, context):
            return "answer"

        with self.target(original), ingestion_receiver(status=401) as (endpoint, requests), self.config(endpoint):
            self.assertEqual(handler({}, FakeContext()), "answer")
        self.assertEqual(len(requests), 2)

    def test_slow_export_cannot_hold_handler_past_configured_drain(self):
        def original(event, context):
            return "answer"

        with self.target(original), ingestion_receiver(delay=0.35) as (endpoint, _), \
                self.config(endpoint, TRACEWORTH_EXPORT_TIMEOUT="0.05"):
            started = time.monotonic()
            self.assertEqual(handler({}, FakeContext(remaining_ms=250)), "answer")
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.3, f"telemetry blocked handler for {elapsed:.3f}s")

    def test_invalid_original_handler_is_a_clear_configuration_error(self):
        def original(event, context):
            return "unused"

        with self.target(original):
            for path in ("", "handle", "absent_package_xyz.handle",
                         f"{self.module_name}.missing", f"{self.module_name}.not_callable",
                         "traceworth.integrations.aws_lambda.handler"):
                with self.subTest(path=path), self.config(
                        TRACEWORTH_ORIGINAL_HANDLER=path):
                    with self.assertRaises(ValueError):
                        handler({}, FakeContext())

    def test_openai_sync_responses_and_chat_capture_model_and_tokens_only(self):
        provider_requests = []

        def provider(request):
            provider_requests.append(request)
            if request.url.path.endswith("/responses"):
                return provider_http.Response(200, json={
                    "id": "resp_test", "object": "response", "created_at": 1,
                    "model": "gpt-test-response", "output": [],
                    "usage": {"input_tokens": 13, "output_tokens": 7, "total_tokens": 20}})
            return provider_http.Response(200, json={
                "id": "chatcmpl_test", "object": "chat.completion", "created": 1,
                "model": "gpt-test-chat", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "private-generated-answer-300"},
                "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}})

        http_client = provider_http.Client(transport=provider_http.MockTransport(provider))
        client = OpenAI(api_key="private-provider-key-862", base_url="https://provider.invalid/v1",
                        http_client=http_client, max_retries=0)

        def original(event, context):
            response = client.responses.create(model="gpt-input-alias",
                                               input="private-prompt-732")
            chat = client.chat.completions.create(model="gpt-input-alias",
                                                   messages=[{"role": "user", "content": "private-chat-991"}])
            return (response.model, chat.choices[0].message.content)

        try:
            with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                    endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
                result = handler({}, FakeContext())
        finally:
            client.close()

        self.assertEqual(result, ("gpt-test-response", "private-generated-answer-300"))
        self.assertEqual(len(provider_requests), 2)
        self.assertEqual(len(requests), 8)
        events = [item["body"]["events"][0] for item in requests]
        root = next(event for event in events
                    if event["event_type"] == "step.started" and event["kind"] == "workflow")
        operations = [event for event in events
                      if event["event_type"] == "step.started" and event["kind"] == "operation"]
        self.assertEqual({event["name"] for event in operations},
                         {"openai.responses.create", "openai.chat.completions.create"})
        self.assertTrue(all(event["parent_step_id"] == root["step_id"] for event in operations))
        usage = [event for event in events if event["event_type"] == "usage.recorded"]
        self.assertEqual({event["model_or_service"]: event["usage_units"] for event in usage},
                         {"gpt-test-response": {"input_tokens": 13, "output_tokens": 7},
                          "gpt-test-chat": {"input_tokens": 11, "output_tokens": 5}})
        self.assertTrue(all(event["provider"] == "openai" and event["amount"] is None
                            for event in usage))
        self.assertTrue(all(event["workflow_id"] == root["workflow_id"] for event in events))
        serialized = json.dumps(events)
        for private_value in ("private-provider-key-862", "private-prompt-732",
                              "private-chat-991", "private-generated-answer-300"):
            self.assertNotIn(private_value, serialized)

    def test_openai_async_responses_and_chat_capture_usage(self):
        async def provider(request):
            if request.url.path.endswith("/responses"):
                return provider_http.Response(200, json={
                    "id": "resp_async", "object": "response", "created_at": 1,
                    "model": "gpt-async-response", "output": [],
                    "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}})
            return provider_http.Response(200, json={
                "id": "chatcmpl_async", "object": "chat.completion", "created": 1,
                "model": "gpt-async-chat", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}})

        async def run():
            async with AsyncOpenAI(api_key="test-provider-key", base_url="https://provider.invalid/v1",
                                   http_client=provider_http.AsyncClient(
                                       transport=provider_http.MockTransport(provider)),
                                   max_retries=0) as client:
                first = await client.responses.create(model="gpt-input-alias", input="secret")
                second = await client.chat.completions.create(
                    model="gpt-input-alias", messages=[{"role": "user", "content": "secret"}])
                return first.model, second.model

        def original(event, context):
            return asyncio.run(run())

        with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
            self.assertEqual(handler({}, FakeContext()),
                             ("gpt-async-response", "gpt-async-chat"))

        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 8)
        usage = [event for event in events if event["event_type"] == "usage.recorded"]
        self.assertEqual({event["model_or_service"]: event["usage_units"] for event in usage},
                         {"gpt-async-response": {"input_tokens": 4, "output_tokens": 2},
                          "gpt-async-chat": {"input_tokens": 8, "output_tokens": 3}})

    def test_openai_patch_is_passive_without_opt_in_and_not_doubled_on_warm_invokes(self):
        def provider(request):
            return provider_http.Response(200, json={
                "id": "resp_repeat", "object": "response", "created_at": 1,
                "model": "gpt-repeat", "output": [],
                "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}})

        client = OpenAI(api_key="test-provider-key", base_url="https://provider.invalid/v1",
                        http_client=provider_http.Client(
                            transport=provider_http.MockTransport(provider)),
                        max_retries=0)

        def original(event, context):
            return client.responses.create(model="gpt-input-alias", input="private").model

        try:
            with self.target(original), ingestion_receiver() as (endpoint, requests):
                with self.config(endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
                    self.assertEqual(handler({}, FakeContext()), "gpt-repeat")
                    self.assertEqual(handler({}, FakeContext()), "gpt-repeat")
                self.assertEqual(len(requests), 10)
                with self.config(endpoint, TRACEWORTH_CAPTURE_OPENAI="false"):
                    self.assertEqual(handler({}, FakeContext()), "gpt-repeat")
        finally:
            client.close()

        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 12)
        self.assertEqual(sum(event["event_type"] == "usage.recorded" for event in events), 2)
        self.assertEqual(sum(event["event_type"] == "step.started" and
                             event["kind"] == "operation" for event in events), 2)

    def test_openai_model_without_provider_usage_does_not_claim_token_counts(self):
        def provider(request):
            return provider_http.Response(200, json={
                "id": "resp_no_usage", "object": "response", "created_at": 1,
                "model": "gpt-no-usage", "output": []})

        client = OpenAI(api_key="test-provider-key", base_url="https://provider.invalid/v1",
                        http_client=provider_http.Client(
                            transport=provider_http.MockTransport(provider)), max_retries=0)

        def original(event, context):
            return client.responses.create(model="gpt-input-alias", input="secret").model

        try:
            with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                    endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
                self.assertEqual(handler({}, FakeContext()), "gpt-no-usage")
        finally:
            client.close()

        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 4)
        self.assertEqual(sum(event["event_type"] == "usage.recorded" for event in events), 0)

    def test_openai_streaming_call_is_passed_through_without_false_completion(self):
        def provider(request):
            return provider_http.Response(200, headers={"content-type": "text/event-stream"},
                                          content=b"data: [DONE]\n\n")

        client = OpenAI(api_key="test-provider-key", base_url="https://provider.invalid/v1",
                        http_client=provider_http.Client(
                            transport=provider_http.MockTransport(provider)), max_retries=0)

        def original(event, context):
            stream = client.responses.create(model="gpt-input-alias", input="private",
                                             stream=True)
            stream.close()
            return "streamed"

        try:
            with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                    endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
                self.assertEqual(handler({}, FakeContext()), "streamed")
        finally:
            client.close()

        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual([event["event_type"] for event in events],
                         ["step.started", "step.finished"])

    def test_openai_provider_exception_propagates_without_message_capture(self):
        def provider(request):
            return provider_http.Response(401, json={
                "error": {"message": "private-provider-error-539", "type": "invalid_api_key"}})

        client = OpenAI(api_key="test-provider-key", base_url="https://provider.invalid/v1",
                        http_client=provider_http.Client(
                            transport=provider_http.MockTransport(provider)), max_retries=0)

        def original(event, context):
            return client.responses.create(model="gpt-input-alias", input="private").model

        try:
            with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                    endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
                with self.assertRaises(AuthenticationError) as caught:
                    handler({}, FakeContext())
        finally:
            client.close()

        self.assertIn("private-provider-error-539", str(caught.exception))
        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 4)
        failures = [event for event in events if event["event_type"] == "step.finished"]
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(event["status"] == "failed" for event in failures))
        self.assertEqual(sum(event["event_type"] == "usage.recorded" for event in events), 0)
        self.assertNotIn("private-provider-error-539", json.dumps(events))


if __name__ == "__main__":
    unittest.main()
