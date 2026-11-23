"""
Pipecat adapter (text harness).

Pipecat's official evals (`pipecat.evals`, the `pipecat eval` CLI) are a
WebSocket client for a bot that is already running, with their own scenario
files. The docs do not describe a way to push text into an in-process
Pipeline for tests. So this adapter does not run your Pipeline: it drives the
same LLM logic through a reply function you write, and keeps the prompt in a
file that your bot also reads.

provider_config:
  prompt_file: prompts/bot_prompt.txt   # your bot loads its system_instruction from here
  respond: my_bot.nexqa_harness:respond  # respond(system_prompt, messages) -> str | dict

A minimal `respond` calls the same model your bot uses, with
`system_instruction = system_prompt` (the docs recommend setting the system
prompt as the LLM service's `system_instruction`; a "system" role message in
LLMContext is deprecated since 1.9.0). See docs/providers/pipecat.md.

This tests the prompt and your tool logic, not the audio pipeline (VAD, STT,
TTS, interruptions). Use Pipecat's own evals for that.

Docs:
- https://docs.pipecat.ai/pipecat/evals/library.md
- https://docs.pipecat.ai/pipecat/learn/context-management.md
- https://docs.pipecat.ai/pipecat/learn/your-first-agent.md
"""

from nexqa.providers.local import CustomHarnessProvider


class PipecatProvider(CustomHarnessProvider):
    name = "pipecat"
    display_name = "Pipecat"
    maturity = "tested-offline"
    test_mode = "text harness: your respond() + simulated caller"
    docs_url = "https://docs.pipecat.ai/pipecat/learn/context-management.md"
