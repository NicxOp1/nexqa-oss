# Vapi

Maturity: **tested-offline**.

## Setup

```bash
export VAPI_API_KEY=...        # private key
nexqa run --provider vapi --agent-id <assistant_id> --spec-path spec.yaml
```

```yaml
provider: vapi
provider_config:
  mode: chat            # chat (default) or simulation
  max_turns: 12         # chat mode
  # simulation mode only:
  personality_id: ...   # simulated-caller personality, created once in the Vapi dashboard
  transport: vapi.webchat
```

## What NEXQA does

- **Prompt**: the system prompt is the `role: "system"` message in `model.messages` of the
  assistant. The docs do not say whether `PATCH /assistant/{id}` merges or replaces `model`
  (a known way to wipe a prompt or tools), so NEXQA reads the assistant and sends back the
  **whole** `model` object (provider, model, tools, toolIds, every message) with only the
  system message changed. No other assistant field is sent.
- **chat mode**: Claude plays the caller; each turn is `POST /chat` with `assistantId`,
  chained with `previousChatId`. Tool calls and tool results come from the chat `output`.
  Tools run for real during chat (Vapi executes them), so point the assistant at test
  endpoints.
- **simulation mode**: per scenario NEXQA creates a simulation scenario (`instructions` = the
  scenario's `user_prompt`, one inline boolean structured-output evaluation per success
  criterion) and a simulation (scenario + your personality), starts
  `POST /eval/simulation/run` against the assistant, polls the run until `ended`, and reads the
  run items (transcript from `metadata.call.messages`, verdict from `results.passed`).

## Needs a live check

- That the `model` object returned by GET is accepted back by PATCH as is.
- That `previousChatId` carries the full conversation context across turns.
- Simulation mode: the inline `structuredOutput` evaluation form (the docs show
  `structuredOutputId`; the inline form is built from the documented fields), and the
  `vapi.webchat` transport.

## Docs

- https://docs.vapi.ai/api-reference/assistants/get
- https://docs.vapi.ai/api-reference/assistants/update
- https://docs.vapi.ai/assistants/quickstart.md
- https://docs.vapi.ai/api-reference/chats/create.md
- https://docs.vapi.ai/api-reference/simulation-scenarios/scenario-controller-create.md
- https://docs.vapi.ai/api-reference/simulations/simulation-controller-create.md
- https://docs.vapi.ai/api-reference/simulation-runs/simulation-run-controller-create
- https://docs.vapi.ai/api-reference/simulation-runs/simulation-run-controller-find-items.md
