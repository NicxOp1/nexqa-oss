# NEXQA

[![CI](https://github.com/NicxOp1/nexqa-oss/actions/workflows/ci.yml/badge.svg)](https://github.com/NicxOp1/nexqa-oss/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

Automated QA and prompt evolution for [Retell AI](https://www.retellai.com) voice agents.

You give NEXQA a voice agent and a YAML spec of what it must do. It runs test calls against the
agent, scores every call, finds the part of the prompt that caused each failure, rewrites only
that part with Claude, and repeats until the agent passes. Guardrails stop it before it makes
the agent worse or spends more than you allowed.

I built it to stop hand-tuning prompts for production voice agents (scheduling, intake, outbound
sales). It works, and it has rough edges. Issues and PRs are welcome.

## How it works

```
 YAML spec ──► prompt split into "genes" ──► Retell batch test calls
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
  than 0.15. A cost meter stops the run at your budget. A linter rejects prompts that grow or
  shrink by more than 50% or leak internal terms, and warns when the identity line disappears.
- **Voice corpus.** A curated set of voice-agent practices (spoken numbers and dates, no
  markdown in TTS, short turns) that the optimizer and linter enforce. See
  [`nexqa/voice_corpus`](nexqa/voice_corpus/nexqa_voice_corpus_curated.md).

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
cp .env.example .env    # set RETELL_API_KEY and ANTHROPIC_API_KEY
nexqa run --spec-path tests/specs/dental_receptionist_spec.yaml --agent-id <retell_agent_id>
```

Test personas live in [`tests/specs/`](tests/specs): `aggressive_skeptic`, `confused_senior`,
`impatient_rushed`, `outbound_sales`. Copy one to start your own.

### What a run costs

A run spends Retell test-call minutes plus Claude tokens, and grows with the number of
scenarios and iterations (up to 5). The cost meter logs the running estimate and stops the run
when it passes `COST_ALERT_THRESHOLD_USD` (default $10). To spend less, set
`CLAUDE_EFFORT=medium`, `CLAUDE_MODEL=claude-sonnet-5-5`, or test fewer scenarios.

## Configuration

Everything is set with environment variables (or `.env`). The ones that matter most:

| Variable | Default | What it does |
|---|---|---|
| `RETELL_API_KEY` | | Required for `run` and `--deploy` |
| `ANTHROPIC_API_KEY` | | Required for `run` |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model for gene tagging, mutation and judging |
| `CLAUDE_EFFORT` | `high` | `low` to `max`. Lower is cheaper and faster |
| `COST_ALERT_THRESHOLD_USD` | `10.0` | Hard stop for one run |
| `NEXQA_STORAGE_DIR` | `./storage` | Logs, reports, cache, prompt history |
| `NEXQA_WEBHOOK_BASE_URL` | `http://localhost:8080` | Where agent tools send calls |

The full list, including the optional API, Airtable, SMTP and webhook settings, is in
[`.env.example`](.env.example).

## Optional components

Install what you need: `pip install -e ".[api]"`, `".[dashboard]"`, `".[webhook]"` or `".[all]"`.

**REST API** (`nexqa/api`). Lets another app start a run (`POST /runs`) and poll it. Runs are
stored in MongoDB. Set `NEXQA_API_KEY` before exposing it beyond localhost.

```bash
uvicorn nexqa.api.server:app --reload        # http://localhost:8000/docs
```

**Dashboard** (`nexqa/dashboard`). A Streamlit view of runs and scores.

```bash
streamlit run nexqa/dashboard/app.py
```

**Webhook server** (`webhook_server/`). A small FastAPI service that receives your agent's tool
calls and routes them to Cal.com, Airtable or Retell SMS, using a per-agent registry. It checks
Retell's `X-Retell-Signature` on every request, so set `RETELL_API_KEY` (the key with the
webhook badge) on the server.

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
  genetics/      gene parser, prompt and tool builders, validator
  optimizer/     gene optimizer, linter, voice corpus
  integrations/  Retell and Claude clients
  api/           FastAPI server (optional)
  dashboard/     Streamlit UI (optional)
  human_qa/      human tester scripts and feedback
webhook_server/  tool-call router: Cal.com, Airtable, Retell SMS (optional)
tests/
  unit/          offline test suite (pytest)
  specs/         example agent specs and test personas
```

## Limitations

- Retell only. Vapi and ElevenLabs agents are not supported yet.
- Scores from the LLM judge vary between runs. Treat a single run as a signal, not a verdict,
  and keep a human in the loop before you deploy a rewritten prompt to production.
- Retell batch tests simulate callers. They do not catch every real-call problem (audio quality,
  background noise, carrier issues).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately, as described in
[SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
