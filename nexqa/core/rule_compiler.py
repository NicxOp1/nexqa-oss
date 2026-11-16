from typing import List, Dict, Any
import re
from nexqa.models.rule_models import CompiledSpec
from nexqa.storage.logger import logger

class CompiledRules:
    """Holds executable versions of the rules"""
    regex_validators: Dict[str, Dict[str, Any]] # {id: {pattern, is_forbidden}}
    tool_validators: List[Dict[str, Any]]  # [{trigger, required_tool, must_occur}]
    sequence_validators: List[List[str]]   # [["tool_a", "tool_b"]] — ordered sequences

    def __init__(self):
        self.regex_validators = {}
        self.tool_validators = []
        self.sequence_validators = []

class RuleCompiler:
    """Compiles abstract rules into executable validators"""
    
    def compile(self, spec: CompiledSpec) -> CompiledRules:
        logger.info("Compiling rules...")
        compiled = CompiledRules()
        
        for rule in spec.hard_rules:
            if rule.regex_pattern:
                try:
                    pattern = re.compile(rule.regex_pattern, re.IGNORECASE)
                    
                    # Heuristic to detect if it's a "forbidden" rule
                    # e.g. "NEVER...", "not '...' ", etc.
                    desc = rule.description.upper()
                    is_forbidden = any(word in desc for word in ["NEVER", "NOT", "FORBIDDEN", "PROHIBITED"])
                    
                    # Special case for HR-010/011 (Natural Dates/Times)
                    if "not '" in rule.description or "spoken naturally" in rule.description:
                        is_forbidden = True

                    compiled.regex_validators[rule.id] = {
                        "pattern": pattern,
                        "is_forbidden": is_forbidden
                    }
                except re.error as e:
                    logger.error(f"Failed to compile regex for rule {rule.id}: {e}")

        # Compile tool dependency rules
        for dep in spec.tool_dependencies:
            compiled.tool_validators.append({
                "trigger": dep.trigger_condition,
                "required_tool": dep.required_tool,
                "must_occur": dep.must_occur,
            })

        # Build sequence validators from hard rules with required_sequence
        for rule in spec.hard_rules:
            if rule.required_sequence and len(rule.required_sequence) > 1:
                compiled.sequence_validators.append(rule.required_sequence)

        return compiled

rule_compiler = RuleCompiler()
