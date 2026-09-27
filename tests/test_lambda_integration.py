"""Independent acceptance checks for the opt-in AWS Lambda handler wrapper."""

import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
from types import ModuleType
import unittest
from unittest.mock import patch

from openai import AsyncOpenAI, AuthenticationError, OpenAI
from langchain_openai import ChatOpenAI

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

    def test_langchain_chat_invoke_captures_response_model_and_usage(self):
        provider_requests = []

        def provider(request):
            provider_requests.append(request)
            return provider_http.Response(200, json={
                "id": "chatcmpl_langchain", "object": "chat.completion", "created": 1,
                "model": "gpt-langchain-response", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "private-langchain-output-871"},
                "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 6, "total_tokens": 23}})

        http_client = provider_http.Client(transport=provider_http.MockTransport(provider))
        async_http_client = provider_http.AsyncClient(
            transport=provider_http.MockTransport(provider))
        llm = ChatOpenAI(model="gpt-input-alias", api_key="private-provider-key-543",
                         base_url="https://provider.invalid/v1", http_client=http_client,
                         http_async_client=async_http_client, max_retries=0,
                         use_responses_api=False)

        def original(event, context):
            return llm.invoke("private-langchain-prompt-309")

        try:
            with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                    endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
                result = handler({}, FakeContext())
        finally:
            http_client.close()
            asyncio.run(async_http_client.aclose())

        self.assertEqual(result.content, "private-langchain-output-871")
        self.assertEqual(result.response_metadata["model_name"], "gpt-langchain-response")
        self.assertEqual(result.usage_metadata["input_tokens"], 17)
        self.assertEqual(len(provider_requests), 1)
        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 5)
        usage = [event for event in events if event["event_type"] == "usage.recorded"]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["model_or_service"], "gpt-langchain-response")
        self.assertEqual(usage[0]["usage_units"],
                         {"input_tokens": 17, "output_tokens": 6})
        child = next(event for event in events if event["event_type"] == "step.started"
                     and event["kind"] == "operation")
        self.assertEqual(usage[0]["step_id"], child["step_id"])
        self.assertEqual(usage[0]["workflow_id"], child["workflow_id"])
        serialized = json.dumps(events)
        for private_value in ("private-provider-key-543", "private-langchain-prompt-309",
                              "private-langchain-output-871"):
            self.assertNotIn(private_value, serialized)

    def test_langchain_chat_ainvoke_captures_response_model_and_usage(self):
        async def provider(request):
            return provider_http.Response(200, json={
                "id": "chatcmpl_langchain_async", "object": "chat.completion", "created": 1,
                "model": "gpt-langchain-async", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "private-async-output-722"},
                "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}})

        async def run():
            http_client = provider_http.Client(
                transport=provider_http.MockTransport(
                    lambda request: provider_http.Response(500)))
            async_http_client = provider_http.AsyncClient(
                transport=provider_http.MockTransport(provider))
            try:
                llm = ChatOpenAI(model="gpt-input-alias", api_key="private-provider-key-642",
                                 base_url="https://provider.invalid/v1", http_client=http_client,
                                 http_async_client=async_http_client, max_retries=0,
                                 use_responses_api=False)
                return await llm.ainvoke("private-async-prompt-842")
            finally:
                http_client.close()
                await async_http_client.aclose()

        def original(event, context):
            return asyncio.run(run())

        with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
            result = handler({}, FakeContext())

        self.assertEqual(result.content, "private-async-output-722")
        self.assertEqual(result.response_metadata["model_name"], "gpt-langchain-async")
        self.assertEqual(result.usage_metadata["input_tokens"], 9)
        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 5)
        usage = [event for event in events if event["event_type"] == "usage.recorded"]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["model_or_service"], "gpt-langchain-async")
        self.assertEqual(usage[0]["usage_units"], {"input_tokens": 9, "output_tokens": 4})
        child = next(event for event in events if event["event_type"] == "step.started"
                     and event["kind"] == "operation")
        self.assertEqual(usage[0]["step_id"], child["step_id"])
        self.assertEqual(usage[0]["workflow_id"], child["workflow_id"])
        serialized = json.dumps(events)
        self.assertNotIn("private-async-prompt-842", serialized)
        self.assertNotIn("private-async-output-722", serialized)
        self.assertNotIn("private-provider-key-642", serialized)

    def test_openai_raw_response_parse_captures_usage_once_without_eager_parse(self):
        def provider(request):
            return provider_http.Response(200, json={
                "id": "chatcmpl_raw", "object": "chat.completion", "created": 1,
                "model": "gpt-raw-response", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "private-raw-output-412"},
                "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})

        client = OpenAI(api_key="private-provider-key-821", base_url="https://provider.invalid/v1",
                        http_client=provider_http.Client(
                            transport=provider_http.MockTransport(provider)), max_retries=0)

        def original(event, context):
            raw = client.chat.completions.with_raw_response.create(
                model="gpt-input-alias", messages=[{"role": "user", "content": "private-raw-773"}])
            first = raw.parse()
            again = raw.parse()
            self.assertIs(first, again)
            return first.choices[0].message.content

        try:
            with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                    endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
                self.assertEqual(handler({}, FakeContext()), "private-raw-output-412")
        finally:
            client.close()

        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 5)
        usage = [event for event in events if event["event_type"] == "usage.recorded"]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["model_or_service"], "gpt-raw-response")
        self.assertEqual(usage[0]["usage_units"], {"input_tokens": 3, "output_tokens": 2})
        child = next(event for event in events if event["event_type"] == "step.started"
                     and event["kind"] == "operation")
        self.assertEqual(usage[0]["step_id"], child["step_id"])
        self.assertEqual(usage[0]["workflow_id"], child["workflow_id"])
        self.assertNotIn("private-raw-773", json.dumps(events))
        self.assertNotIn("private-raw-output-412", json.dumps(events))
        self.assertNotIn("private-provider-key-821", json.dumps(events))

    def test_openai_async_raw_response_repeated_parse_captures_once(self):
        async def provider(request):
            return provider_http.Response(200, json={
                "id": "chatcmpl_raw_async", "object": "chat.completion", "created": 1,
                "model": "gpt-raw-async", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "private-raw-async-output-630"},
                "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}})

        async def run():
            async with AsyncOpenAI(
                    api_key="test-provider-key", base_url="https://provider.invalid/v1",
                    http_client=provider_http.AsyncClient(
                        transport=provider_http.MockTransport(provider)),
                    max_retries=0) as client:
                raw = await client.chat.completions.with_raw_response.create(
                    model="gpt-input-alias",
                    messages=[{"role": "user", "content": "private-raw-async-prompt-517"}])
                first = raw.parse()
                second = raw.parse()
                self.assertIs(first, second)
                return first.choices[0].message.content

        def original(event, context):
            return asyncio.run(run())

        with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
            self.assertEqual(handler({}, FakeContext()), "private-raw-async-output-630")

        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 5)
        usage = [event for event in events if event["event_type"] == "usage.recorded"]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["model_or_service"], "gpt-raw-async")
        self.assertEqual(usage[0]["usage_units"], {"input_tokens": 12, "output_tokens": 3})
        child = next(event for event in events if event["event_type"] == "step.started"
                     and event["kind"] == "operation")
        self.assertEqual(usage[0]["step_id"], child["step_id"])
        self.assertNotIn("private-raw-async-prompt-517", json.dumps(events))
        self.assertNotIn("private-raw-async-output-630", json.dumps(events))

    def test_langchain_provider_failure_preserves_exception_and_hides_message(self):
        def provider(request):
            return provider_http.Response(401, json={
                "error": {"message": "private-langchain-provider-error-611",
                          "type": "invalid_api_key"}})

        http_client = provider_http.Client(transport=provider_http.MockTransport(provider))
        async_http_client = provider_http.AsyncClient(
            transport=provider_http.MockTransport(provider))
        llm = ChatOpenAI(model="gpt-input-alias", api_key="test-provider-key",
                         base_url="https://provider.invalid/v1", http_client=http_client,
                         http_async_client=async_http_client, max_retries=0,
                         use_responses_api=False)

        try:
            with self.assertRaises(AuthenticationError) as baseline:
                llm.invoke("private-langchain-prompt-512")

            # A fresh client models first use after Lambda installs the adapter.
            from traceworth.integrations.openai_sdk import install
            self.assertTrue(install())
            fresh_http_client = provider_http.Client(
                transport=provider_http.MockTransport(provider))
            fresh_async_http_client = provider_http.AsyncClient(
                transport=provider_http.MockTransport(provider))
            fresh_llm = ChatOpenAI(
                model="gpt-input-alias", api_key="test-provider-key",
                base_url="https://provider.invalid/v1", http_client=fresh_http_client,
                http_async_client=fresh_async_http_client, max_retries=0,
                use_responses_api=False)

            def original(event, context):
                return fresh_llm.invoke("private-langchain-prompt-512")

            with self.target(original), ingestion_receiver() as (endpoint, requests), self.config(
                    endpoint, TRACEWORTH_CAPTURE_OPENAI="true"):
                with self.assertRaises(AuthenticationError) as instrumented:
                    handler({}, FakeContext())
        finally:
            http_client.close()
            asyncio.run(async_http_client.aclose())
            if "fresh_http_client" in locals():
                fresh_http_client.close()
                asyncio.run(fresh_async_http_client.aclose())

        self.assertEqual(str(instrumented.exception), str(baseline.exception))
        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 4)
        self.assertEqual(sum(event["event_type"] == "usage.recorded" for event in events), 0)
        self.assertEqual({event["status"] for event in events
                          if event["event_type"] == "step.finished"}, {"failed"})
        self.assertNotIn("private-langchain-provider-error-611", json.dumps(events))
        self.assertNotIn("private-langchain-prompt-512", json.dumps(events))

    def test_cold_lambda_import_installs_hook_before_module_level_langchain_client(self):
        # A client created while importing the business module caches OpenAI's
        # with_raw_response wrapper. Verify the first invocation in a fresh
        # process instruments that cached method, including its failure path.
        source = '''
from importlib.metadata import version
from langchain_openai import ChatOpenAI
if version("openai").split(".", 1)[0] == "2":
    import httpx as provider_http
else:
    import httpx2 as provider_http

def provider(request):
    if b"cause-error" in request.content:
        return provider_http.Response(401, json={
            "error": {"message": "private-cold-error-905", "type": "invalid_api_key"}})
    return provider_http.Response(200, json={
        "id": "chatcmpl_cold", "object": "chat.completion", "created": 1,
        "model": "gpt-cold-response", "choices": [{"index": 0,
        "message": {"role": "assistant", "content": "private-cold-output-200"},
        "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}})

http_client = provider_http.Client(transport=provider_http.MockTransport(provider))
async_http_client = provider_http.AsyncClient(transport=provider_http.MockTransport(provider))
llm = ChatOpenAI(model="gpt-input-alias", api_key="test-provider-key",
                 base_url="https://provider.invalid/v1", http_client=http_client,
                 http_async_client=async_http_client, max_retries=0,
                 use_responses_api=False)

def handle(event, context):
    prompt = "cause-error" if event["fail"] else "private-cold-prompt-419"
    return llm.invoke(prompt).content
'''
        script = '''
from openai import AuthenticationError
from traceworth.integrations.aws_lambda import handler
try:
    handler({"fail": True}, None)
except AuthenticationError as error:
    assert "private-cold-error-905" in str(error)
else:
    raise AssertionError("original provider exception was suppressed")
assert handler({"fail": False}, None) == "private-cold-output-200"
'''
        with TemporaryDirectory() as directory:
            Path(directory, "cold_langchain_target.py").write_text(source, encoding="utf-8")
            with ingestion_receiver() as (endpoint, requests):
                env = os.environ.copy()
                env.update({"PYTHONPATH": directory + os.pathsep + env.get("PYTHONPATH", ""),
                            "TRACEWORTH_ORIGINAL_HANDLER": "cold_langchain_target.handle",
                            "TRACEWORTH_APPLICATION": "test-app",
                            "TRACEWORTH_ENDPOINT": endpoint,
                            "TRACEWORTH_API_KEY": "test-ingestion-key",
                            "TRACEWORTH_CAPTURE_OPENAI": "true"})
                result = subprocess.run([sys.executable, "-c", script], env=env,
                                        capture_output=True, text=True, timeout=30)

        self.assertEqual(result.returncode, 0, result.stderr)
        events = [item["body"]["events"][0] for item in requests]
        self.assertEqual(len(events), 9)
        root_starts = [event for event in events if event["event_type"] == "step.started"
                       and event["kind"] == "workflow"]
        self.assertEqual(len(root_starts), 2)
        failed_workflow = root_starts[0]["workflow_id"]
        failure_finishes = [event for event in events if event["event_type"] == "step.finished"
                            and event["workflow_id"] == failed_workflow]
        self.assertEqual(len(failure_finishes), 2)
        self.assertTrue(all(event["status"] == "failed" for event in failure_finishes))
        usage = [event for event in events if event["event_type"] == "usage.recorded"]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["model_or_service"], "gpt-cold-response")
        self.assertEqual(usage[0]["usage_units"], {"input_tokens": 7, "output_tokens": 2})
        serialized = json.dumps(events)
        for private_value in ("private-cold-error-905", "private-cold-output-200",
                              "private-cold-prompt-419"):
            self.assertNotIn(private_value, serialized)


if __name__ == "__main__":
    unittest.main()
