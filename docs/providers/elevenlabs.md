# ElevenLabs Agents

Maturity: **tested-offline**.

## Setup

```bash
export ELEVENLABS_API_KEY=...
nexqa run --provider elevenlabs --agent-id <agent_id> --spec-path spec.yaml
```

```yaml
provider: elevenlabs
provider_config:
  max_turns: 10                     # simulation_max_turns per test
  # base_url: https://api.eu.residency.elevenlabs.io   # data residency
  # tool_mock_config: {mocking_strategy: all, fallback_strategy: raise_error}
```

## What NEXQA does

- **Prompt**: `conversation_config.agent.prompt.prompt`. The docs do not say whether
  `PATCH /v1/convai/agents/{id}` deep-merges a partial `conversation_config`, so NEXQA reads
  the agent and sends back the **whole** `conversation_config` with only the prompt text
  changed. `platform_settings`, `workflow`, name and tags are not sent.
- **Tests**: native agent testing. One `simulation` test per scenario
  (`simulation_scenario` = the scenario's `user_prompt`, `success_conditions` = its success
  criteria), then `POST /v1/convai/agents/{id}/run-tests`, polled at
  `GET /v1/convai/test-invocations/{id}`. Each run's `agent_responses` becomes the
  transcript; `condition_result` is kept as the platform verdict. The deprecated
  simulate-conversation endpoint is not used.

## Needs a live check

- That PATCH accepts the full `conversation_config` read from GET (output vs input schema).
- That `agent_responses` holds the whole simulated conversation (caller and agent turns). The
  docs list its fields but do not say so.
- Which agent version the tests run against (draft or published).

## Docs

- https://elevenlabs.io/docs/eleven-agents/api-reference/agents/get.md
- https://elevenlabs.io/docs/eleven-agents/api-reference/agents/update.md
- https://elevenlabs.io/docs/eleven-agents/api-reference/tests/create.md
- https://elevenlabs.io/docs/eleven-agents/api-reference/tests/run-tests.md
- https://elevenlabs.io/docs/eleven-agents/api-reference/tests/test-invocations/get.md
