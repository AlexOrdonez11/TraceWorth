"""Synthetic usage only. No providers are called and no real costs are reported."""
from traceworth import JsonlExporter, TraceWorth


def demonstrate(application, workflow, operation):
    with TraceWorth(application, JsonlExporter("demo-events.jsonl")) as client:
        @client.operation(operation)
        def perform():
            client.record_usage("synthetic", "demo-model", {"input_tokens": 100, "output_tokens": 40})

        @client.workflow(workflow)
        def request():
            perform()
            client.record_outcome("demo_accepted", True)

        request()
    print(application, client.diagnostics)


if __name__ == "__main__":
    demonstrate("myhandyai", "repair_request", "generate_repair_steps")
    demonstrate("clientsignaleq", "conversation_analysis", "analyze_conversation")
    demonstrate("analyticsai", "answer_question", "generate_query")
