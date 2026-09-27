# AWS Lambda integration: first pilot

TraceWorth can measure a Python Lambda invocation without editing the function's
business logic. Add the TraceWorth package to the function deployment (or a
compatible layer), set the Lambda handler to
`traceworth.integrations.aws_lambda.handler`, and identify the existing handler
through configuration. The wrapper passes the original `event` and `context`
objects through and returns the original result. It records the invocation's
start, finish, duration, and success/failure status. Optional OpenAI SDK capture
can also record the returned model and token counts from supported calls. Neither
path records event payloads, return values, prompts, generated text, exception
messages, inferred prices, or business outcomes.

## Before configuring MyHandyAI

The TraceWorth FastAPI ingestion service must be running, reachable at an HTTPS
`/api/events` URL, and have an application and an ingestion-only key for the
right account. The current AWS staging foundation does not yet run the API or
serve the dashboard, so its CloudFront hostname is not yet a working endpoint.
Keep the key outside source control and deployment artifacts. This repository's
package is not yet published to a package index. One way to create a Python
Lambda layer from the current checkout on Windows is:

```powershell
.\.venv\Scripts\python.exe -m pip install --target local-data/traceworth-layer/python .
Compress-Archive -Path local-data/traceworth-layer/python -DestinationPath local-data/traceworth-layer.zip
```

Attach that layer to the test Lambda using your existing deployment workflow,
and verify that its runtime can import `traceworth`. Pin the TraceWorth commit
or wheel used for each release; rebuild the layer when TraceWorth changes.
The `local-data` output is local build material and must not be committed.

For the current private pilot, AWS WAF allows only the owner's public IP. A
MyHandyAI Lambda needs an approved, stable egress IP and an outbound route to
CloudFront before it can deliver events. A VPC-attached Lambda normally needs a
NAT route for public internet access; an unattached Lambda has internet access
but does not provide a stable egress IP for this allowlist. Review the resulting
network cost before changing MyHandyAI's VPC configuration. See the
[staging setup](staging-setup.md) for the TraceWorth side of this deployment.

## Configure one Lambda

Keep the original handler in the package. For example, if the current Lambda
handler setting is `my_app.handlers.answer`, change only the handler setting to
`traceworth.integrations.aws_lambda.handler` and add these environment values:

| Name | Example | Purpose |
| --- | --- | --- |
| `TRACEWORTH_ORIGINAL_HANDLER` | `my_app.handlers.answer` | Existing callable, which receives the same `event` and `context` |
| `TRACEWORTH_APPLICATION` | `myhandyai-stage` | Slug of the application associated with the ingestion key |
| `TRACEWORTH_ENDPOINT` | `https://<cloudfront-domain>/api/events` | Full HTTPS ingestion URL |
| `TRACEWORTH_API_KEY` | The application's ingestion key | Secret; never commit or log its value |
| `TRACEWORTH_ENVIRONMENT` | `staging` | Optional; defaults to `production` |
| `TRACEWORTH_CONFIGURATION_ID` | `release-1` | Optional stable release/configuration label |
| `TRACEWORTH_EXPORT_TIMEOUT` | `1.0` | Optional maximum seconds to wait for delivery after the handler; defaults to 1.0 |
| `TRACEWORTH_CAPTURE_OPENAI` | `true` | Optional; capture supported direct OpenAI Python SDK calls made inside the invocation |

Deploy the configuration with the same release as the packaged TraceWorth code.
For multiple Lambda functions, repeat the handler setting and identify each
original handler separately. Use one application/key per client application,
and use a staging application/key for the pilot. Do not place the key in a
frontend build, repository, container image, or Terraform state. Lambda
environment variables are encrypted at rest, but AWS recommends Secrets Manager
for API keys; a later integration can fetch a secret at runtime so the key need
not be stored as a Lambda environment value.

With `TRACEWORTH_CAPTURE_OPENAI=true` and a compatible OpenAI Python SDK
packaged with the app, direct non-streaming `responses.create` and
`chat.completions.create`
calls (sync and async) get child operation spans. When the returned object
includes both a model and token usage, TraceWorth records the model name and
provider-reported input/output token counts. That lets MyHandyAI use the adapter
without adding a tracing call beside every OpenAI call. It does not inspect
request arguments or response content. Streaming calls, other OpenAI APIs,
custom HTTP calls, and SDK wrappers that bypass these methods are outside this
adapter. If the response has no usage, no model-only usage record is emitted;
the report remains partial. Costs are unknown until a separate, explicit
pricing source is supplied.

The adapter is tested against OpenAI Python 2.54.0 and 3.19.2. It accepts those
minor-version lines (`2.54.x` and `3.19.x`) and disables itself with a sanitized
warning for other versions.
Check MyHandyAI's installed `openai` version before the pilot (for example,
`python -m pip show openai`) and pin a tested version in its deployment. The
TraceWorth `[openai]` extra installs the tested 3.19.x range when the client
app does not already provide it. There is no need to replace a working 2.54.x
installation for this adapter.

The wrapper creates one workflow per invocation. It gives the workflow a
controlled name derived from the configured original handler, not from event
content. The original handler still owns its own exceptions and return values.
Invalid telemetry configuration or an export failure leaves application behavior
unchanged; a missing or invalid original handler remains an application
configuration error. Check TraceWorth delivery diagnostics and backend ingestion
to confirm capture, since a successful Lambda invocation alone does not prove
that events arrived.

## Local verification, then pilot

1. Package TraceWorth alongside a copy of a test Lambda and verify that Python
   can import both `traceworth.integrations.aws_lambda` and the original handler.
2. Run the wrapper against a disposable local backend account/application or a
   loopback test receiver. Verify the original result and one completed workflow.
3. Trigger a controlled failure and verify the original exception still reaches
   Lambda while TraceWorth records a failed workflow, without recording event
   contents or exception text.
4. Deploy to a staging Lambda, enable network access through the pilot WAF, and
   verify received events in the authenticated TraceWorth dashboard. Inspect
   CloudWatch Lambda warnings for pending, dropped, or failed exports. Compare
   CloudWatch invocation volume against captured dashboard workflows before
   relying on reports; the dashboard does not infer missing invocations.

Delivery remains best effort: the exporter has no retries or durable spool, and
the per-invocation drain has a finite deadline. A timeout, network/WAF failure,
or process termination can leave an incomplete workflow. The wrapper does not
discover arbitrary internal functions or retries, and the OpenAI adapter covers
only the calls described above. Whether an answer helped a user still requires
an explicit application outcome signal.

AWS references: [Python handler signatures](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html),
[environment-variable security](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html),
and [VPC internet access](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc-internet.html).
OpenAI response fields are documented in the [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
and [Chat Completions API](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create).
