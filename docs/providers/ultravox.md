# Ultravox

Maturity: **tested-offline**.

Ultravox has no testing API (its testing page is marked under construction), so NEXQA plays
the caller over a text-only call.

## Setup

```bash
pip install -e ".[ultravox]"     # websockets
export ULTRAVOX_API_KEY=...
nexqa run --provider ultravox --agent-id <agent_id> --spec-path spec.yaml
```

```yaml
provider: ultravox
provider_config:
  max_turns: 12
  reply_timeout_s: 30       # wait for each agent turn
  greeting_timeout_s: 8     # wait for an agent-first greeting
  # max_duration: 300s
```

## What NEXQA does

- **Prompt**: `callTemplate.systemPrompt`. Updated with `PATCH /api/agents/{id}` and
  `{"callTemplate": {"systemPrompt": ...}}`, the partial body the agents guide shows. Agent
  changes only affect new calls.
- **Tests**: per scenario, `POST /api/agents/{id}/calls` with a `serverWebSocket` medium,
  `mediumRestriction.allowedMediums: ["MESSAGE_MEDIUM_TEXT"]` and
  `initialOutputMedium: MESSAGE_MEDIUM_TEXT`. NEXQA joins `joinUrl`, sends
  `user_text_message` data messages, reads `transcript` messages until the agent's turn is
  `final`, and ends with `hang_up`. Afterwards it reads `GET /api/calls/{id}/messages` (all
  pages, tool calls and results included) and `GET /api/calls/{id}` (`endReason`,
  `billedDuration`) as the conversation of record.

## Needs a live check

- Whether a text-only call over `serverWebSocket` needs a silent audio stream (the docs say
  the server expects one second of audio per second, and are silent on text-only calls).
- Whether `initialOutputMedium` takes `MESSAGE_MEDIUM_TEXT` or `"text"` (the guide and the
  OpenAPI schema differ).
- The format of `billedDuration`.

## Docs

- https://docs.ultravox.ai/api-reference/agents/agents-get.md
- https://docs.ultravox.ai/api-reference/agents/agents-patch.md
- https://docs.ultravox.ai/agents/building-and-editing-agents.md
- https://docs.ultravox.ai/api-reference/agents/agents-calls-post.md
- https://docs.ultravox.ai/agents/making-calls.md
- https://docs.ultravox.ai/apps/websockets.md
- https://docs.ultravox.ai/apps/datamessages.md
- https://docs.ultravox.ai/api-reference/calls/calls-messages-list.md
- https://docs.ultravox.ai/api-reference/calls/calls-get.md
