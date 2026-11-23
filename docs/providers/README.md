# Providers

NEXQA talks to every voice platform through one adapter interface
([`nexqa/providers/base.py`](../../nexqa/providers/base.py)). Scoring, genes, the linter,
guardrails and the voice corpus never see platform APIs.

Pick a platform in the spec (both keys are optional; the default is Retell, so older specs
keep working):

```yaml
provider: vapi
provider_config:
  mode: chat
  max_turns: 12
```

or on the command line: `nexqa run --provider vapi --agent-id <id> --spec-path spec.yaml`.
`nexqa providers` prints the table below from the code.

## Matrix

| Provider | How test conversations run | Prompt field NEXQA rewrites | Maturity |
|---|---|---|---|
| [Retell AI](retell.md) | Native batch tests | `general_prompt` on the Retell LLM | verified-live |
| [Vapi](vapi.md) | Chat API + simulated caller, or native Simulations | `model.messages[role=system]` | tested-offline |
| [ElevenLabs Agents](elevenlabs.md) | Native agent tests (simulation type) | `conversation_config.agent.prompt.prompt` | tested-offline |
| [Bland AI](bland.md) | Native Agent Testing scenarios (persona or pathway) | persona `personality_prompt`, or V2 `settings.systemPrompt` | tested-offline |
| [Synthflow](synthflow.md) | Native Simulations | assistant `agent.prompt` | tested-offline |
| [Ultravox](ultravox.md) | Text-only call over WebSocket + simulated caller | `callTemplate.systemPrompt` | tested-offline |
| [LiveKit Agents](livekit.md) | In-process `AgentSession` text mode + simulated caller | your prompt file | tested-offline |
| [Pipecat](pipecat.md) | Your `respond()` function + simulated caller | your prompt file | tested-offline |
| [Custom](custom.md) | Your `respond()` function + simulated caller | your prompt file | tested-offline |

**verified-live**: used against the real platform. **tested-offline**: written from the
platform's official docs (cited in each adapter's module docstring) and covered by mocked-HTTP
tests, but not yet run against a live account. If you run one live, please open an issue or PR
with what happened, so the row can move up.

## Native tests vs simulated caller

When a platform has an API that runs a scripted test conversation (Retell, ElevenLabs, Bland,
Synthflow, Vapi Simulations), NEXQA uses it: it creates one platform test per spec scenario,
with the scenario's `user_prompt` as the simulated caller and its `expected_outcome` and
`critical_checkpoints` as success criteria.

When it has none (Ultravox, self-hosted frameworks, Vapi chat mode), NEXQA plays the caller
itself: Claude reads the scenario's `user_prompt` and talks to the agent turn by turn over the
platform's text channel. It stops when the caller says it is done, the agent hangs up, or
`provider_config.max_turns` (default 12) is reached. Settings: `SIMULATOR_MODEL`,
`SIMULATOR_EFFORT` (default `low`).

Text conversations test the prompt and the tool logic. They do not test audio: speech
recognition, TTS, latency, interruptions or background noise.

Either way NEXQA scores every conversation itself, on the same four axes. A platform's own
pass/fail verdict is kept on the conversation (`platform_passed`) for reference only.

## Prompt updates keep everything else

`update_prompt` must change only the prompt. Where a platform's docs do not say whether a
partial update merges or replaces a nested object (Vapi `model`, ElevenLabs
`conversation_config`, Bland V2 snapshots), the adapter reads the object, changes the prompt,
and sends the whole object back. Each provider page says what is sent.

## Writing an adapter

Subclass `VoiceProvider` (or `HTTPProvider` for a REST API, or `SimulatedCallerProvider` when
you only have a text channel), then register it in `nexqa/providers/__init__.py`:

| Method | Job |
|---|---|
| `get_prompt(agent_id)` | Return the current system prompt |
| `update_prompt(agent_id, prompt)` | Replace only the prompt |
| `resolve_target(agent_id)` | Validate the agent, return what the runner needs |
| `register_scenarios(agent_id, spec, target)` | Create platform tests; skip (log) a scenario that fails |
| `start_run(suite)` | Start one pass, return a handle |
| `wait_for_results(suite, handle, poll_interval, timeout)` | Return `SuiteRun(conversations, billed_minutes)` |

Return each conversation as a `Conversation` (turns with `role` "agent" or "user", tool calls
with name, arguments and result, end reason, duration). Cite the docs you used in the module
docstring, add offline tests with a fake session (see `tests/unit/providers/_fakes.py`), and
mark the adapter `tested-offline` until someone runs it live.
