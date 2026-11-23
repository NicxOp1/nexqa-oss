# Contributing to NEXQA

Thanks for helping. Bug reports, new test personas and fixes are all welcome.

## Set up

```bash
git clone https://github.com/NicxOp1/nexqa-oss.git
cd nexqa-oss
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Before you open a PR

```bash
ruff check .
pytest
```

Both run in CI on Linux (Python 3.11 to 3.13) and Windows. The unit tests are offline: they
must never call a voice platform or Claude or need an API key. Mock the client instead (see
`tests/unit/test_claude_client.py`, and `tests/unit/providers/_fakes.py` for HTTP adapters).

## Good first contributions

- **New test personas.** Add a YAML file to `tests/specs/` for a caller type we don't cover yet.
- **Voice corpus rules.** Add a practice to `nexqa/voice_corpus/nexqa_voice_corpus_curated.md`
  with a short reason and, ideally, a linter check.
- **Connectors.** Add a webhook connector in `webhook_server/connectors/` (see `base.py`).
- **Live reports for an adapter.** Most adapters are `tested-offline`. Running one against a
  live account and reporting what happened (or fixing what broke) is the most useful PR right
  now. Each `docs/providers/<name>.md` lists the open questions.
- **New platforms.** See [Writing an adapter](docs/providers/README.md#writing-an-adapter).
  Take every API shape from the platform's official docs and cite them in the module docstring.

## Guidelines

- Keep PRs focused: one fix or feature per PR.
- Add or update a test for any behavior you change.
- Never commit API keys, real call transcripts or customer data. Use the fictional fixtures in
  `tests/fixtures/`.
- If you change a prompt that NEXQA sends to Claude, say in the PR what you measured before and
  after.

## Reporting bugs

Open an issue with what you ran, what you expected and what happened. Include the NEXQA version,
your Python version, and logs with keys and caller data removed.
