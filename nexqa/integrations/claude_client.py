import anthropic
from nexqa.storage.config import Config
from nexqa.core.cost_meter import cost_meter
from nexqa.storage.logger import logger
import json
from typing import Dict, Any, Optional

class ClaudeClient:
    """Wrapper for Anthropic's Claude API"""

    def __init__(self):
        Config.validate()
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.CLAUDE_MODEL or "claude-sonnet-4-6"

    def _track_usage(self, message) -> None:
        """Extract token usage from API response and feed to cost_meter."""
        usage = getattr(message, "usage", None)
        if usage:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            cost_meter.add_tokens(input_tokens, output_tokens)
            logger.debug(
                f"Claude tokens: in={input_tokens}, out={output_tokens}"
            )

    def complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        """Call Claude for a completion"""
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                temperature=temperature,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
            self._track_usage(message)
            return message.content[0].text
        except Exception as e:
            logger.error(f"Claude API Error: {str(e)}")
            raise

    def parse_document(self, document_content: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Specific method for document ingestion with schema enforcement"""
        system_prompt = f"""
        You are an expert Document Ingestion Agent for Voice AI QA.
        Extract rules, scenarios, and dependencies from the provided QA Specification.
        Return ONLY valid JSON matching this schema:
        {json.dumps(schema, indent=2)}
        """
        
        response = self.complete(system_prompt, document_content, temperature=0.0)  # cost tracked inside complete()
        try:
            import re
            # 1. Try regex for ```json ... ``` (standard block)
            json_pattern = r"```(?:json)?\s*(.*?)\s*```"
            match = re.search(json_pattern, response, re.DOTALL)

            if match:
                clean_response = match.group(1)
            else:
                # 2. Fallback: Manual stripping if regex failed (e.g. malformed closing)
                clean_response = response.strip()
                if clean_response.startswith("```json"):
                    clean_response = clean_response[7:]
                elif clean_response.startswith("```"):
                    clean_response = clean_response[3:]
                
                if clean_response.endswith("```"):
                    clean_response = clean_response[:-3]

            clean_response = clean_response.strip()
            return json.loads(clean_response)
        except (json.JSONDecodeError, AttributeError) as e:
            logger.error(f"Failed to parse Claude response as JSON: {response[:500]}...") 
            raise ValueError(f"Invalid JSON response from Claude: {e}")

claude_client = ClaudeClient()
