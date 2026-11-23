"""
Thin wrapper around the Anthropic Messages API.

The underlying client is created on first use, so importing NEXQA (for tests,
`nexqa --help`, or offline work) never requires an API key.
"""

import json
import re
from typing import Any, Dict, Optional

import anthropic

from nexqa.core.cost_meter import cost_meter
from nexqa.storage.config import Config
from nexqa.storage.logger import logger


class ClaudeRefusalError(RuntimeError):
    """Raised when Claude declines a request (stop_reason == "refusal")."""


class ClaudeClient:
    """Wrapper for Anthropic's Claude API."""

    def __init__(self, client: Optional[anthropic.Anthropic] = None) -> None:
        self._client = client
        self.model = Config.CLAUDE_MODEL

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            Config.validate(retell=False)
            self._client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        return self._client

    def _track_usage(self, message: Any) -> None:
        """Extract token usage from an API response and feed it to the cost meter."""
        usage = getattr(message, "usage", None)
        if usage:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            cost_meter.add_tokens(input_tokens, output_tokens)
            logger.debug(f"Claude tokens: in={input_tokens}, out={output_tokens}")

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        *,
        effort: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        """Return Claude's text answer for one system + user prompt.

        `temperature` is accepted for backwards compatibility and ignored:
        current Claude models do not take sampling parameters. Use
        CLAUDE_EFFORT to trade depth for cost instead. `effort` and `model`
        override the defaults for one call (the simulated caller uses them).
        """
        try:
            with self.client.messages.stream(
                model=model or self.model,
                max_tokens=Config.CLAUDE_MAX_TOKENS,
                thinking={"type": "adaptive"},
                output_config={"effort": effort or Config.CLAUDE_EFFORT},
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                message = stream.get_final_message()
        except anthropic.APIStatusError as e:
            logger.error(f"Claude API error {e.status_code}: {e.message}")
            raise
        except anthropic.APIConnectionError as e:
            logger.error(f"Claude connection error: {e}")
            raise

        self._track_usage(message)

        if message.stop_reason == "refusal":
            raise ClaudeRefusalError("Claude declined this request")
        if message.stop_reason == "max_tokens":
            logger.warning(
                "Claude hit CLAUDE_MAX_TOKENS; the answer may be truncated. "
                "Raise CLAUDE_MAX_TOKENS if this repeats."
            )

        # Thinking blocks come before the text, so never index content[0].
        return "".join(b.text for b in message.content if b.type == "text")

    def parse_document(self, document_content: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Extract rules, scenarios and dependencies from a QA spec as JSON."""
        system_prompt = f"""
        You are an expert Document Ingestion Agent for Voice AI QA.
        Extract rules, scenarios, and dependencies from the provided QA Specification.
        Return ONLY valid JSON matching this schema:
        {json.dumps(schema, indent=2)}
        """
        response = self.complete(system_prompt, document_content)
        try:
            return extract_json(response)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse Claude response as JSON: {response[:500]}...")
            raise ValueError(f"Invalid JSON response from Claude: {e}")


def extract_json(text: str) -> Any:
    """Parse JSON from a model answer, tolerating ```json fences around it."""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    candidate = match.group(1) if match else text
    candidate = candidate.strip()
    if not candidate:
        raise ValueError("empty response")
    return json.loads(candidate)


claude_client = ClaudeClient()
