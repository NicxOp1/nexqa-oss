# Bland AI

Maturity: **tested-offline**.

Bland's Agent Testing runs scenarios against a **persona** or a **pathway**. The docs show no
API to test a V2 agent (`/v2/agents`), so the adapter works on personas by default, where the
prompt and the tests address the same object.

## Setup

```bash
export BLAND_API_KEY=...      # sent as `authorization: <key>`, no "Bearer"
nexqa run --provider bland --agent-id <persona_id> --spec-path spec.yaml
```

```yaml
provider: bland
provider_config:
  target: persona        # persona (default) or agent_v2
  max_turns: 20          # per scenario, max 50
  # agent_v2 only: what the tests run against
  # persona_id: ...
  # pathway_id: ...
  # branch: ...
```

## What NEXQA does

- **Prompt, persona** (default): `personality_prompt` of the persona's current draft
  version. Updated with `PATCH /v1/personas/{id}`, sending only `name` (required by the
  endpoint) and `personality_prompt`.
- **Prompt, agent_v2**: `snapshot.settings.systemPrompt` of the latest version. A change
  saves a new version (`POST /v2/agents/{id}/versions`) with the full snapshot and
  `parent_version_id` / `parent_revision` as a compare-and-set guard. Promoting that version
  to an environment is up to you.
- **Tests**: one Agent Testing scenario per spec scenario (`tester_persona_prompt` = the
  scenario's `user_prompt`), started with `POST /v1/agent-testing/scenarios/{id}/run`,
  polled at `GET /v1/agent-testing/runs/{run_id}`. `chat_history` becomes the transcript.
  NEXQA does not create Bland assertions; it scores the conversation itself.

## Needs a live check

- The shape of `GET /v1/personas/{id}` (the adapter reads
  `current_draft_version.personality_prompt`, as returned by the PATCH endpoint).
- Whether a scenario run tests the persona draft or a published version (`version_number`).
- Rate limits when many scenarios start at once.

## Docs

- https://docs.bland.ai/api-v1/patch/personas-id.md
- https://docs.bland.ai/api-v2/get/agents-id-versions-latest.md
- https://docs.bland.ai/api-v2/post/agents-id-versions.md
- https://docs.bland.ai/tutorials/scenarios.md
- https://docs.bland.ai/api-v1/post/agent-testing-scenarios.md
- https://docs.bland.ai/api-v1/post/agent-testing-scenarios-run.md
- https://docs.bland.ai/api-v1/get/agent-testing-runs-id.md
