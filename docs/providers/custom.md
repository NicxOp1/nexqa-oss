# Custom (any framework)

Maturity: **tested-offline**.

For an agent NEXQA has no adapter for, give it the prompt file and a reply function. It works
the same way as the [Pipecat](pipecat.md) adapter.

```yaml
provider: custom
provider_config:
  prompt_file: prompts/agent.txt
  respond: my_agent.harness:respond    # respond(system_prompt, messages) -> str | dict
  max_turns: 12
```

`messages` is a list of `{"role": "user" | "assistant", "content": str}`. Return the reply
text, or `{"text": ..., "tool_calls": [{"name", "arguments", "result"}], "ended": bool}`.
The function may be sync or async. From Python you can pass the function itself instead of the
`"module:function"` string.

If your platform has an API, a real adapter is better: see
[Writing an adapter](README.md#writing-an-adapter).
