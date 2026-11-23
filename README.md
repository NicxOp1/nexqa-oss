# NEXQA

[![CI](https://github.com/NicxOp1/nexqa-oss/actions/workflows/ci.yml/badge.svg)](https://github.com/NicxOp1/nexqa-oss/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

Open-source QA and prompt evolution for voice AI agents: Retell, Vapi, ElevenLabs, Bland,
Synthflow, Ultravox, LiveKit Agents and Pipecat.

You give NEXQA a voice agent and a YAML spec of what it must do. It runs test conversations
against the agent, scores every one, finds the part of the prompt that caused each failure,
rewrites only that part with Claude, and repeats until the agent passes. Guardrails stop it
before it makes the agent worse or spends more than you allowed.

I built it to stop hand-tuning prompts for production voice agents (scheduling, intake, outbound
sales). It works, and it has rough edges. Issues and PRs are welcome, especially reports from
running an adapter against a live account.

## Supported platforms

| Platform | How test conversations run | Maturity | Setup |
|---|---|---|---|
| Retell AI | Native batch tests | verified-live | [docs](docs/providers/retell.md) |
| Vapi | Chat API + simulated caller, or native Simulations | tested-offline | [docs](docs/providers/vapi.md) |
| ElevenLabs Agents | Native agent tests (simulation type) | tested-offline | [docs](docs/providers/elevenlabs.md) |
| Bland AI | Native Agent Testing (persona or pathway) | tested-offline | [docs](docs/providers/bland.md) |
| Synthflow | Native Simulations | tested-offline | [docs](docs/providers/synthflow.md) |
| Ultravox | Text-only call over WebSocket + simulated caller | tested-offline | [docs](docs/providers/ultravox.md) |
| LiveKit Agents | In-process `AgentSession` text mode + simulated caller | tested-offline | [docs](docs/providers/livekit.md) |
| Pipecat | Your reply function + simulated caller | tested-offline | [docs](docs/providers/pipecat.md) |
| Anything else | Your reply function + simulated caller | tested-offline | [docs](docs/providers/custom.md) |

**verified-live** means it has been used against the real platform. **tested-offline** means
the adapter was written from the platform's official API docs (cited in its module docstring)
and is covered by mocked-HTTP tests, but has not been run against a live account yet. Each
setup page lists what still needs a live check. `nexqa providers` prints this table.

Where a platform can run a scripted test call itself, NEXQA uses that. Where it cannot, Claude
plays the caller over the platform's text channel. Text conversations test the prompt and the
tool logic, not audio. More in [docs/providers](docs/providers/README.md).

## How it works

```
 YAML spec ──► prompt split into "genes" ──► test conversations on your platform
                                                    │
                    ┌───────────────────────────────┘
                    ▼
            4-axis scoring per call ──► pass? ──► done
                    │ fail
                    ▼
     find the gene that failed ──► Claude rewrites ONLY that gene
                    │
                    ▼
     linter + regression check + budget check ──► next iteration
```

- **Genes.** A prompt is split into tagged sections: `IDENTITY`, `PERSONALITY`, `FLOW`, `RULES`,
  `GUARDRAILS`, `OBJECTIONS`, `TOOLS`, `CLOSING`. Each has a priority and a mutation budget.
  `IDENTITY` and `GUARDRAILS` are never rewritten.
- **Scoring.** Every call gets four scores: deterministic rules (right tool calls, forbidden
  phrases, latency), semantic intent (LLM judge), conversational quality and human-likeness.
- **Targeted mutation.** Only the gene behind a failure is rewritten. The other genes stay the
  same, so a fix to objection handling cannot change the greeting.
- **Guardrails.** A baseline regression check blocks any change that drops a scenario by more
  than 0.15 and rolls the prompt back. A cost meter stops the run at your budget. A linter
  rejects prompts that grow or shrink by more than 50% or leak internal terms, and warns when
  the identity line disappears.
- **Voice corpus.** A curated set of voice-agent practices (spoken numbers and dates, no
  markdown in TTS, short turns) that the optimizer and linter enforce. See
  [`nexqa/voice_corpus`](nexqa/voice_corpus/nexqa_voice_corpus_curated.md).
- **Provider adapters.** All of the above is platform-neutral. One adapter per platform reads
  and writes the prompt (changing nothing else on the agent) and returns each test
  conversation in one normalized shape. See [`nexqa/providers`](nexqa/providers).

## Quick start

Requires Python 3.11+.

```bash
git clone https://github.com/NicxOp1/nexqa-oss.git
cd nexqa-oss
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                               # offline, no API keys needed
```

### 1. Build an agent from a spec (no API keys)

```bash
nexqa create --spec-path tests/specs/example_agent_spec.yaml
```

This writes `build/sarah_prompt.txt` and `build/sarah_tools.json`. Read them, edit the spec, run
it again. Add `--deploy` to create the agent in Retell (needs `RETELL_API_KEY`).

### 2. Run the QA loop against a live agent

```bash
cp .env.example .env    # set ANTHROPIC_API_KEY and your platform's key

# Retell (the default)
nexqa run --spec-path tests/specs/dental_receptionist_spec.yaml --agent-id <retell_agent_id>

# Any other platform
nexqa run --provider vapi --spec-path my_spec.yaml --agent-id <assistant_id>
```

Or put the platform in the spec, so the spec says where it runs:

```yaml
provider: elevenlabs        # default: retell
provider_config:            # platform options, see docs/providers/<name>.md
  max_turns: 10
```

For platforms other than Retell, NEXQA shows the diff and asks before it deploys each rewrite.
`--auto-apply` skips the question. Test personas live in [`tests/specs/`](tests/specs):
`aggressive_skeptic`, `confused_senior`, `impatient_rushed`, `outbound_sales`. Copy one to
start your own.

### What a run costs

A run spends test-call time on your platform plus Claude tokens, and grows with the number of
scenarios and iterations (up to 5). The cost meter logs the running estimate and stops the run
when it passes `COST_ALERT_THRESHOLD_USD` (default $10). Set `PLATFORM_PRICE_PER_MINUTE` to
your platform's per-minute price so the estimate is right. Text conversations driven by the
simulated caller bill no call minutes, but each caller turn is a short Claude call. To spend
less, set `CLAUDE_EFFORT=medium`, `CLAUDE_MODEL=claude-sonnet-5-5`, or test fewer scenarios.

## Configuration

Everything is set with environment variables (or `.env`). The ones that matter most:

| Variable | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | | Required for `run` |
| `RETELL_API_KEY`, `VAPI_API_KEY`, `ELEVENLABS_API_KEY`, `BLAND_API_KEY`, `SYNTHFLOW_API_KEY`, `ULTRAVOX_API_KEY` | | The key of the platform you test |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model for gene tagging, mutation and judging |
| `CLAUDE_EFFORT` | `high` | `low` to `max`. Lower is cheaper and faster |
| `SIMULATOR_MODEL` / `SIMULATOR_EFFORT` | `CLAUDE_MODEL` / `low` | The simulated caller |
| `COST_ALERT_THRESHOLD_USD` | `10.0` | Hard stop for one run |
| `PLATFORM_PRICE_PER_MINUTE` | `0.12` | Price of one billed test-call minute |
| `NEXQA_STORAGE_DIR` | `./storage` | Logs, reports, cache, prompt history |
| `NEXQA_WEBHOOK_BASE_URL` | `http://localhost:8080` | Where agent tools send calls |

The full list, including the optional API, Airtable, SMTP and webhook settings, is in
[`.env.example`](.env.example).

## Optional components

Install what you need: `pip install -e ".[api]"`, `".[dashboard]"`, `".[webhook]"`,
`".[ultravox]"` or `".[all]"`.

**REST API** (`nexqa/api`). Lets another app start a run (`POST /runs`, with an optional
`provider`) and poll it. Runs are stored in MongoDB. Set `NEXQA_API_KEY` before exposing it
beyond localhost.

```bash
uvicorn nexqa.api.server:app --reload        # http://localhost:8000/docs
```

**Dashboard** (`nexqa/dashboard`). A Streamlit view of runs and scores.

```bash
streamlit run nexqa/dashboard/app.py
```

**Webhook server** (`webhook_server/`). A small FastAPI service that receives your agent's tool
calls and routes them to Cal.com, Airtable or Retell SMS, using a per-agent registry. Today it
speaks Retell's tool-call format and checks Retell's `X-Retell-Signature` on every request, so
set `RETELL_API_KEY` (the key with the webhook badge) on the server.

```bash
uvicorn webhook_server.app:app --port 8080
# or
docker build -f webhook_server/Dockerfile -t nexqa-webhooks . && docker run -p 8080:8080 --env-file .env nexqa-webhooks
```

[`render.yaml`](render.yaml) deploys it to Render. After deploying, set `PUBLIC_BASE_URL` on the
server and `NEXQA_WEBHOOK_BASE_URL` for the CLI to the deployed URL.

**Human QA** (`nexqa/human_qa`). Generates call scripts for human testers and turns their notes
into issues the optimizer can act on.

## End-to-end example

[`tests/test_dental_e2e.py`](tests/test_dental_e2e.py) walks through the whole loop with a
fictional dental receptionist, using mocked transcripts and tools instead of real calls:

```bash
python -m tests.test_dental_e2e --phase create   # offline, no API calls
python -m tests.test_dental_e2e                  # scoring + optimization, calls Claude
```

## Project layout

```
nexqa/
  core/          engine, scoring, cost meter, regression tracker, validators
  providers/     one adapter per voice platform + the simulated caller
  genetics/      gene parser, prompt and tool builders, validator
  optimizer/     gene optimizer, linter, voice corpus
  integrations/  Retell and Claude clients
  api/           FastAPI server (optional)
  dashboard/     Streamlit UI (optional)
  human_qa/      human tester scripts and feedback
webhook_server/  tool-call router: Cal.com, Airtable, Retell SMS (optional)
docs/providers/  per-platform setup
tests/
  unit/          offline test suite (pytest), incl. every adapter with mocked HTTP
  specs/         example agent specs and test personas
```

## Limitations

- Only the Retell adapter has been run against a live account. The others follow the
  platforms' official docs and pass offline tests; each setup page lists the open questions.
- `nexqa create --deploy`, the phone-number picker and the webhook server are still
  Retell-only. Testing and prompt evolution work on every platform above.
- Text conversations (simulated caller) test the prompt and tools, not audio. Platform-run
  simulations do not catch every real-call problem either (audio quality, background noise,
  carrier issues).
- Scores from the LLM judge vary between runs. Treat a single run as a signal, not a verdict,
  and keep a human in the loop before you deploy a rewritten prompt to production.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), and
[Writing an adapter](docs/providers/README.md#writing-an-adapter) for new platforms. Report
security issues privately, as described in [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
