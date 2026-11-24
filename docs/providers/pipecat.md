# Pipecat

Maturity: **tested-offline**.

Pipecat's own evals (`pipecat.evals`, the `pipecat eval` CLI) connect over WebSocket to a bot
that is already running, with their own scenario files. The docs do not describe pushing text
into an in-process Pipeline for tests, so NEXQA does not run your Pipeline. It drives your
bot's LLM logic through a small reply function you write, and keeps the prompt in a file your
bot also reads.

## Setup

```python
# my_bot/nexqa_harness.py
from openai import AsyncOpenAI

client = AsyncOpenAI()

async def respond(system_prompt: str, messages: list[dict]) -> str:
    # Same model and settings as the bot's LLM service.
    out = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}, *messages],
    )
    return out.choices[0].message.content
```

In the bot, load the same file as the LLM service's `system_instruction` (the docs recommend
setting the system prompt there; a "system" message in `LLMContext` is deprecated since 1.9.0).

```yaml
provider: pipecat
provider_config:
  prompt_file: prompts/bot_prompt.txt
  respond: my_bot.nexqa_harness:respond
  max_turns: 12
```

`respond(system_prompt, messages)` may be sync or async. It returns the reply text, or a dict
`{"text": ..., "tool_calls": [{"name", "arguments", "result"}], "ended": bool}` if you want
tool calls scored.

## Limits

This tests the prompt and your tool logic, not the audio pipeline (VAD, STT, TTS,
interruptions). Use Pipecat's evals for that.

## Docs

- https://docs.pipecat.ai/pipecat/evals/library.md
- https://docs.pipecat.ai/pipecat/learn/context-management.md
- https://docs.pipecat.ai/pipecat/learn/your-first-agent.md
