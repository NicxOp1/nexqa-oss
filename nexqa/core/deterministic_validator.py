from typing import List, Dict, Any
from nexqa.core.rule_compiler import CompiledRules
from nexqa.models.scenario_models import ValidationResult, SimulationResult
from nexqa.storage.logger import logger

class DeterministicValidator:
    """Runs compiled rules against simulation transcripts"""

    def validate(self, simulation: SimulationResult, rules: CompiledRules) -> ValidationResult:
        logger.info(f"Validating simulation {simulation.scenario_id}...")

        failed_rules = []
        details = {}

        transcript_text = simulation.transcript

        # Check Regex Rules
        for rule_id, rule_data in rules.regex_validators.items():
            pattern = rule_data["pattern"]
            is_forbidden = rule_data["is_forbidden"]

            match = pattern.search(transcript_text)

            if is_forbidden and match:
                logger.warning(f"Rule {rule_id} failed: Forbidden pattern found.")
                failed_rules.append(rule_id)
                details[rule_id] = "Forbidden pattern found in transcript"
            elif not is_forbidden and not match:
                logger.warning(f"Rule {rule_id} failed: Required pattern not found.")
                failed_rules.append(rule_id)
                details[rule_id] = "Required pattern not found in transcript"

        # Check Tool Usage
        tool_names_called = self._extract_tool_names(simulation.tool_calls)

        # Tool dependency validation: required_tool must appear when trigger is met
        for dep in rules.tool_validators:
            trigger = dep["trigger"]
            required_tool = dep["required_tool"]
            must_occur = dep["must_occur"]

            # Check if the trigger condition is met (tool was called or keyword in transcript)
            trigger_met = (
                trigger in tool_names_called
                or trigger.lower() in transcript_text.lower()
            )

            if not trigger_met:
                continue  # Trigger not met, rule doesn't apply

            if required_tool not in tool_names_called:
                rule_id = f"TOOL_DEP_{required_tool}"
                logger.warning(f"Rule {rule_id} failed: {required_tool} not called (trigger: {trigger})")
                failed_rules.append(rule_id)
                details[rule_id] = f"Tool '{required_tool}' was required ({must_occur}) but never called. Trigger: '{trigger}'"
            elif must_occur == "before_response":
                # Verify tool was called before agent gave a substantive response about the trigger
                tool_idx = self._first_tool_index(simulation.tool_calls, required_tool)
                trigger_mention_idx = self._first_transcript_mention(transcript_text, trigger)
                if trigger_mention_idx >= 0 and tool_idx > trigger_mention_idx:
                    rule_id = f"TOOL_ORDER_{required_tool}"
                    logger.warning(f"Rule {rule_id} failed: {required_tool} called after responding about '{trigger}'")
                    failed_rules.append(rule_id)
                    details[rule_id] = f"Tool '{required_tool}' was called after agent already responded about '{trigger}'. Should be called before responding."

        # Tool sequence validation: tools must appear in correct order
        for sequence in rules.sequence_validators:
            violation = self._check_sequence(tool_names_called, sequence)
            if violation:
                rule_id = f"TOOL_SEQ_{'_'.join(sequence[:2])}"
                logger.warning(f"Rule {rule_id} failed: {violation}")
                failed_rules.append(rule_id)
                details[rule_id] = violation

        passed = len(failed_rules) == 0
        return ValidationResult(
            passed=passed,
            failed_rules=failed_rules,
            details=details
        )

    def _extract_tool_names(self, tool_calls: List[Any]) -> List[str]:
        """Extract tool names from tool_calls (handles both dict and string entries)."""
        names = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                names.append(tc.get("name", "unknown"))
            elif isinstance(tc, str):
                names.append(tc)
        return names

    def _first_tool_index(self, tool_calls: List[Any], tool_name: str) -> int:
        """Return index of first occurrence of tool_name in tool_calls, or -1."""
        for i, tc in enumerate(tool_calls):
            name = tc.get("name", tc) if isinstance(tc, dict) else tc
            if name == tool_name:
                return i
        return -1

    def _first_transcript_mention(self, transcript: str, term: str) -> int:
        """Return character index of first mention of term in agent responses, or -1."""
        lower_transcript = transcript.lower()
        lower_term = term.lower()
        # Only look in Agent: lines
        for line in transcript.split("\n"):
            if line.startswith("Agent:"):
                idx = line.lower().find(lower_term)
                if idx >= 0:
                    return lower_transcript.find(line.lower())
        return -1

    def _check_sequence(self, tool_names: List[str], required_sequence: List[str]) -> str | None:
        """Verify tools were called in the required order. Returns error message or None."""
        # Filter to only tools that appear in the sequence
        relevant = [t for t in tool_names if t in required_sequence]

        if not relevant:
            # None of the sequence tools were called — might not be applicable
            return None

        # Check that all tools in sequence were called
        missing = [t for t in required_sequence if t not in relevant]
        if missing:
            return f"Required tool sequence {required_sequence}: missing tools {missing}"

        # Check order: first occurrence of each must be in sequence order
        indices = {}
        for t in required_sequence:
            try:
                indices[t] = relevant.index(t)
            except ValueError:
                pass

        for i in range(len(required_sequence) - 1):
            a, b = required_sequence[i], required_sequence[i + 1]
            if a in indices and b in indices and indices[a] > indices[b]:
                return f"Tool '{a}' must be called before '{b}', but was called after"

        return None

deterministic_validator = DeterministicValidator()
