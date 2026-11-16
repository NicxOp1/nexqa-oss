from pathlib import Path
from nexqa.integrations.claude_client import claude_client
from nexqa.models.rule_models import CompiledSpec
from nexqa.storage.logger import logger
import json
import docx

class SpecIngestor:
    """Ingests QA documents and compiles them into structured rules."""
    
    def ingest(self, file_path: Path) -> CompiledSpec:
        """Read file and parse with Claude"""
        logger.info(f"Ingesting spec from: {file_path}")
        
        if not file_path.exists():
            raise FileNotFoundError(f"Spec file not found: {file_path}")
            
        content = self._read_file(file_path)
        
        # Define the schema we want Claude to populate
        schema = CompiledSpec.model_json_schema()
        
        # If file is already JSON, parse it directly. Otherwise use Claude.
        if file_path.suffix.lower() == ".json":
            try:
                parsed_data = json.loads(content)
                logger.info("Loaded spec directly from JSON.")

                # If spec has objectives but no scenarios, generate them with Claude
                if parsed_data.get("objectives") and not parsed_data.get("scenarios"):
                    logger.info(f"Spec has {len(parsed_data['objectives'])} objectives but no scenarios. Generating with Claude...")
                    parsed_data = self._generate_scenarios_from_objectives(parsed_data)

            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON file: {e}")
        else:
            # Call Claude for unstructured files
            parsed_data = claude_client.parse_document(content, schema)
        
        # Validate and return
        try:
            compiled = CompiledSpec(**parsed_data)
            compiled.raw_text = content # Store original text if needed
            logger.info("Spec successfully compiled.")
            return compiled
        except Exception as e:
            logger.error(f"Validation Error: {e}")
            raise

    def _generate_scenarios_from_objectives(self, spec_data: dict) -> dict:
        """Use Claude to generate test scenarios and rules from high-level agent objectives."""
        objectives = spec_data.get("objectives", [])
        agent_name = spec_data.get("agent_name", "Voice Agent")
        agent_type = spec_data.get("agent_type", "general")

        objectives_text = "\n".join(
            f"- {o['id']}: {o['description']} (Success: {o.get('success_criteria', o['description'])})"
            for o in objectives
        )

        system_prompt = """You are a Voice AI QA test designer. Given agent objectives, generate test scenarios and validation rules.
Return ONLY valid JSON with this exact structure:
{
  "scenarios": [
    {
      "id": "scenario_1",
      "name": "Short descriptive name",
      "description": "What this scenario tests",
      "user_prompt": "You are a caller who wants to [specific goal]. You should [persona details]. Speak naturally and provide information when asked.",
      "expected_outcome": "The agent should [expected behavior]",
      "critical_checkpoints": ["checkpoint 1", "checkpoint 2"]
    }
  ],
  "hard_rules": [
    {
      "id": "rule_1",
      "description": "Description of what must/must not happen",
      "forbidden_terms": ["term1", "term2"],
      "category": "compliance"
    }
  ],
  "soft_rules": [
    {
      "id": "soft_1",
      "description": "Guideline description",
      "evaluation_criteria": "How to evaluate this",
      "category": "tone"
    }
  ]
}

Generate scenarios based on the objectives. Include a mix of:
1. Happy path - caller cooperates fully
2. Edge case - caller is uncertain or asks unusual questions
3. Adversarial - caller is difficult, off-topic, or tries to confuse the agent

Generate 2-3 hard rules and 2-3 soft rules based on the objectives."""

        # Respect max_scenarios from spec
        max_scenarios = spec_data.get("max_scenarios", 6)
        system_prompt += f"\n\nIMPORTANT: Generate at most {max_scenarios} scenarios total (not per objective)."

        user_prompt = f"""Agent: {agent_name} (type: {agent_type})

Objectives:
{objectives_text}

Generate comprehensive test scenarios and rules for this voice AI agent."""

        try:
            response = claude_client.complete(system_prompt, user_prompt)

            # Extract JSON from response
            json_str = response.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
            json_str = json_str.strip()

            generated = json.loads(json_str)
            logger.info(f"Generated {len(generated.get('scenarios', []))} scenarios, {len(generated.get('hard_rules', []))} hard rules, {len(generated.get('soft_rules', []))} soft rules")
            # Preserve config fields from original spec
            for key in ('max_iterations', 'max_scenarios', 'prompt'):
                if key in spec_data and key not in generated:
                    generated[key] = spec_data[key]
            return generated

        except Exception as e:
            logger.error(f"Failed to generate scenarios from objectives: {e}")
            # Fallback: create minimal scenario from first objective
            fallback_obj = objectives[0] if objectives else {"id": "default", "description": "Complete the conversation"}
            result = {
                "scenarios": [{
                    "id": f"auto_{fallback_obj['id']}",
                    "name": f"Test: {fallback_obj['description']}",
                    "description": f"Verify agent can: {fallback_obj['description']}",
                    "user_prompt": f"You are a potential customer calling about {fallback_obj['description'].lower()}. Be cooperative and provide information when asked.",
                    "expected_outcome": fallback_obj.get("success_criteria", fallback_obj["description"]),
                    "critical_checkpoints": [fallback_obj["description"]]
                }],
                "hard_rules": [],
                "soft_rules": []
            }
            # Preserve config fields from original spec
            for key in ('max_iterations', 'max_scenarios', 'prompt'):
                if key in spec_data:
                    result[key] = spec_data[key]
            return result

    def _read_file(self, file_path: Path) -> str:
        if file_path.suffix == ".txt":
            return file_path.read_text(encoding="utf-8")
        elif file_path.suffix == ".md":
            return file_path.read_text(encoding="utf-8")
        elif file_path.suffix == ".json":
            return file_path.read_text(encoding="utf-8")
        elif file_path.suffix == ".docx":
            try:
                doc = docx.Document(file_path)
                full_text = []
                for para in doc.paragraphs:
                    full_text.append(para.text)
                return "\n".join(full_text)
            except Exception as e:
                logger.error(f"Error reading .docx file: {e}")
                raise
        return file_path.read_text(encoding="utf-8")

spec_ingestor = SpecIngestor()
