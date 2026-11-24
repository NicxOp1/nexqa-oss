# LiveKit Agents

Maturity: **tested-offline**.

NEXQA runs your agent in-process with LiveKit's text-mode test API (`AgentSession` with an LLM,
`session.run(user_input=...)`): no room, no audio. Claude plays the caller.

## Setup

Install `livekit-agents` and the plugin for your LLM in the same environment as NEXQA. Keep
the agent's instructions in a file, and expose a factory that builds the agent from them:

```python
# my_agent/agent.py
from livekit.agents import Agent

def build_agent(instructions: str) -> Agent:
    return Agent(instructions=instructions, tools=[...])
```

```yaml
provider: livekit
provider_config:
  prompt_file: prompts/agent_instructions.txt   # your entrypoint reads this file too
  agent_factory: my_agent.agent:build_agent
  llm: openai/gpt-4.1-mini                      # anything AgentSession(llm=...) accepts
  max_turns: 12
```

```bash
nexqa run --provider livekit --agent-id front-desk --spec-path spec.yaml
```

`--agent-id` is only a label for logs and prompt history.

## What NEXQA does

- **Prompt**: read from and written to `prompt_file`. Commit it, so every rewrite is a diff.
- **Tests**: per scenario, a fresh `AgentSession(llm=...)`, `await session.start(agent)`, then
  one `session.run(user_input=...)` per caller turn. From `RunResult.events` it reads
  assistant messages, function calls (`name`, `arguments`) and their outputs.
- Tools run for real unless you mock them (LiveKit's `mock_tools` works inside your factory).

## Needs a live check

- The event `type` names on `RunResult.events` ("message", "function_call",
  "function_call_output"). The testing guide shows the matching helpers; the RunResult
  reference page was not available when this adapter was written.

## Docs

- https://docs.livekit.io/testing/unit-tests.md
- https://docs.livekit.io/agents/logic/sessions.md
- https://docs.livekit.io/agents/logic/agents-handoffs.md
