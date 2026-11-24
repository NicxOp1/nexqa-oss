# Retell AI

Maturity: **verified-live** (the code path NEXQA used before 0.3.0, moved behind the adapter
interface unchanged; a unit test checks the normalized output against the old parsing).

## Setup

```bash
export RETELL_API_KEY=...
nexqa run --spec-path spec.yaml --agent-id <agent_id>
```

No `provider:` key is needed: Retell is the default. `--agent-id` also accepts an `llm_...` id.

## What NEXQA does

- **Prompt**: reads the agent's `response_engine.llm_id`, then reads and PATCHes
  `general_prompt` on that Retell LLM. Only `general_prompt` is sent, so tools, states and
  voice settings stay. Agents on a custom LLM (`llm_websocket_url`) are not supported.
- **Tests**: one test case definition per scenario (`user_prompt` is the simulated caller,
  the success criteria become `metrics`), one batch test per iteration, polled until done.
  Billed minutes come from `batch_test_summary.total_duration_seconds`.

`nexqa run` for Retell keeps its interactive loop (confirm before each update). The REST API
and `QAEngine` run the same adapter through the shared engine.

## Docs

- https://docs.retellai.com/api-references/get-agent
- https://docs.retellai.com/api-references/update-retell-llm
- https://docs.retellai.com/api-references/create-test-case-definition
- https://docs.retellai.com/api-references/create-batch-test
