# NEXQA

Automated QA and prompt evolution for [Retell AI](https://www.retellai.com) voice agents.

NEXQA treats a voice agent prompt as a set of "genes" (identity, personality, flow, rules,
objections, tools). It runs test conversations against the agent, scores each one, finds the
gene that caused a failure, rewrites only that section with Claude, and repeats until the agent
passes or a guardrail stops the loop.

I built it to stop hand-tuning prompts for production voice agents (scheduling, intake, outbound
sales). It is a working tool, not a polished product: expect rough edges.

## What it does

- **Gene parsing**: splits a plain-text prompt into XML genes with priority, mutability and a
  mutation budget (`nexqa/genetics`).
- **Test loop**: creates Retell test cases from a YAML spec, runs them as a batch, and waits for
  every run to finalize (`nexqa/core/engine.py`).
- **4-axis scoring**: deterministic rules (tool calls, forbidden phrases, latency), semantic intent
  (LLM judge), conversational quality, and human-likeness (`nexqa/core/score_engine.py`).
- **Targeted mutation**: rewrites only the failing gene and keeps immutable genes untouched
  (`nexqa/optimizer`).
- **Guardrails**: regression tracking against a baseline, cost meter (Claude tokens + Retell
  minutes), and a linter for voice anti-patterns such as markdown in TTS output or prompt bloat.
- **Voice corpus**: a curated set of voice-agent best practices the optimizer and linter enforce
  (`nexqa/voice_corpus`).
- **Agent builder**: generates a full prompt and Retell custom tools from a YAML spec and can deploy
  it (`nexqa create --deploy`).
- **Webhook server**: a small FastAPI service that routes agent tool calls to Cal.com, Airtable and
  Retell SMS, with a per-agent registry (`webhook_server/`).
- **Human QA**: generates call scripts for human testers and feeds their pass/fail notes back into
  the loop.

## Quick start

Requires Python 3.11+.

```bash
git clone https://github.com/NicxOp1/nexqa.git
cd nexqa
pip install -r requirements.txt
pip install -e .
cp .env.example .env   # fill in RETELL_API_KEY and ANTHROPIC_API_KEY
```

Build an agent from a spec (prints the prompt and tools; add `--deploy` to create it in Retell):

```bash
nexqa create --spec-path tests/specs/example_agent_spec.yaml
```

Run the QA and optimization loop against an existing agent:

```bash
nexqa run --spec-path tests/specs/dental_receptionist_spec.yaml --agent-id <retell_agent_id>
```

Adversarial personas live in `tests/specs/` (`aggressive_skeptic`, `confused_senior`,
`impatient_rushed`, `outbound_sales`).

## API and dashboard

```bash
uvicorn nexqa.api.server:app --reload        # http://localhost:8000/docs
streamlit run nexqa/dashboard/app.py
```

The API stores runs in MongoDB, so another app can start a run (`POST /runs`) and poll it.

## Webhook server

```bash
pip install -r webhook_server/requirements-webhook.txt
uvicorn webhook_server.app:app --port 8080
```

`render.yaml` deploys it to Render as a Docker service. Set `PUBLIC_BASE_URL` on the server and
`NEXQA_WEBHOOK_BASE_URL` for the CLI to the deployed URL.

## Tests

```bash
pytest tests/
```

`tests/test_dental_e2e.py` runs the pipeline against a fictional dental receptionist with mocked
transcripts and tools.

## Layout

```
nexqa/
  core/          engine, scoring, cost meter, regression tracker, validators
  genetics/      gene parser, prompt and tool builders
  optimizer/     gene optimizer, linter, voice corpus
  integrations/  Retell and Claude clients
  api/           FastAPI server
  dashboard/     Streamlit UI
  human_qa/      human tester scripts and feedback
webhook_server/  tool-call router (Cal.com, Airtable, Retell SMS)
tests/           specs, fixtures, e2e test
```

## License

MIT
