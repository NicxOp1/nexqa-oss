# Changelog

## 0.3.0

NEXQA is now platform-agnostic: the same QA and prompt-evolution loop runs on Retell, Vapi,
ElevenLabs Agents, Bland, Synthflow, Ultravox, LiveKit Agents, Pipecat, or your own harness.

### Added
- Provider adapter layer (`nexqa/providers`). Every platform implements one interface: read
  the prompt, replace only the prompt, run the spec's scenarios as test conversations, and
  return each one as a normalized conversation (turns, tool calls, timings, end reason).
- Adapters: `vapi` (Chat API + simulated caller, or native Simulations), `elevenlabs`
  (native agent tests), `bland` (native Agent Testing on personas or pathways), `synthflow`
  (native Simulations), `ultravox` (text-only WebSocket call), `livekit` (in-process
  `AgentSession` text mode), `pipecat` and `custom` (your reply function). All are written
  from the platforms' official docs, cited in each module, and marked `tested-offline` until
  run against a live account. See `docs/providers/`.
- Simulated caller: for platforms without a native test runner, Claude plays the caller from
  the scenario's `user_prompt` (`SIMULATOR_MODEL`, `SIMULATOR_EFFORT`).
- Spec keys `provider:` and `provider_config:`. The default is `retell`, so existing specs
  run unchanged.
- `nexqa providers` lists the platforms and adapter maturity. `nexqa run --provider` and
  `--auto-apply`; `provider` on `POST /runs`; `?provider=` on `GET /agents/{id}/prompt`;
  `genetize.py --provider`.
- `PLATFORM_PRICE_PER_MINUTE` for the cost meter, and the `ultravox` extra (websockets).
- `.env.example` is now in the repo (the README pointed to it, but `.gitignore` excluded it).
- Offline tests for every adapter with mocked HTTP (84 tests in total).

### Changed
- `QAEngine` talks to a `VoiceProvider` instead of the Retell client, and takes an optional
  `provider` argument and a `confirm_update` gate. Retell behavior is unchanged: the Retell
  adapter is the old engine code, and a test checks its output against the old parsing.


### Fixed
- Claude calls work with current models. NEXQA no longer sends `temperature`, which current
  models reject, and reads the answer text after any thinking blocks instead of taking the first
  block. The default model is now `claude-opus-5-5` (the old default was not a valid model ID).
- `email_notifier.py` failed to import on Python 3.11 (an f-string syntax added in 3.12).
- The webhook server's "current time" fell back to a fixed EST offset and ignored daylight
  saving time. It now uses `zoneinfo`.
- Human QA script generation and feedback triage called Claude and then discarded the answer.
  They now parse it, and fall back to a basic script or issue when parsing fails.
- Report HTML now escapes scenario names and issue text.

### Security
- The webhook server verifies Retell's `X-Retell-Signature` on every tool call. Set
  `VERIFY_SIGNATURES=false` only for local tests.
- `POST /admin/refresh-cache` needs `ADMIN_TOKEN` and is off when the token is unset.
- Tool-call payloads (which can hold caller PII) are logged only at `DEBUG`.
- The REST API compares API keys in constant time and warns at startup when no key is set.
- The webhook Docker image runs as a non-root user.

### Changed
- Importing NEXQA or running `nexqa --help` no longer needs API keys. Clients connect on first
  use.
- `nexqa create` writes the generated prompt and tools to `build/` (change it with `--out`).
- Runtime files go to `./storage`, or to `NEXQA_STORAGE_DIR`.
- Claude and Retell prices for the cost meter can be set with environment variables.
- `CLAUDE_EFFORT` sets how hard Claude thinks (`low` to `max`).
- Optional dependencies are split into extras: `api`, `dashboard`, `webhook`, `all`, `dev`.

### Added
- Offline unit test suite (36 tests) and GitHub Actions CI on Linux and Windows.
- `CONTRIBUTING.md`, `SECURITY.md` and issue templates.

## 0.1.0

- First public release.
