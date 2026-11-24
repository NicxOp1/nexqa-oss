# Synthflow

Maturity: **tested-offline**.

## Setup

```bash
export SYNTHFLOW_API_KEY=...
nexqa run --provider synthflow --agent-id <model_id> --spec-path spec.yaml
```

```yaml
provider: synthflow
provider_config:
  # suite_id: ...                               # needed for v2 simulation suites
  # base_url: https://api.eu.synthflow.ai/v2    # regional API
```

## What NEXQA does

- **Prompt**: `agent.prompt` of the assistant (`GET /v2/assistants/{model_id}`). Updated with
  `PUT /v2/assistants/{model_id}` and `{"agent": {"prompt": ...}}`. The docs say only the
  provided parameters are updated, so nothing else is sent.
- **Tests**: native Simulations. One simulation case per scenario (`prompt` = the scenario's
  `user_prompt`, `success_criteria` = its success criteria, `call_success_type: all`), one
  simulation per case against the agent, polled at `GET /v2/simulations/{id}`. The
  `timeline` becomes the transcript; `success_criteria_analysis` is kept as the platform
  verdict. Simulations may place billed calls on your Synthflow account.

## Needs a live check

- The id field of a created simulation case: the schema says `simulation_case_id`, the
  example says `id`. The adapter accepts both.
- The values of `timeline[].sender_type` (not listed in the docs). The adapter treats senders
  containing "agent", "bot", "assistant" or "target" as the agent, and tool or action events
  as tool calls.

## Docs

- https://docs.synthflow.ai/api-reference/platform-api/agents/get-assistant
- https://docs.synthflow.ai/api-reference/platform-api/agents/update-assistant
- https://docs.synthflow.ai/api-reference/platform-api/simulations/create-simulation-case
- https://docs.synthflow.ai/api-reference/platform-api/simulations/start-simulation
- https://docs.synthflow.ai/api-reference/platform-api/simulations/get-simulation
