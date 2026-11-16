from typing import List, Dict, Any
from pydantic import BaseModel

class VoiceGuideline(BaseModel):
    id: str
    name: str
    description: str
    check_logic: str # Description of how to check this programmatically or via LLM

class VoiceSkill:
    """
    Expert system for Voice AI Prompting.
    Contains heuristics and best practices for conversational agents.
    """
    
    GUIDELINES = [
        VoiceGuideline(
            id="conciseness",
            name="Optimize for Latency",
            description="Responses should be short to reduce TTS generation time. Avoid monologues.",
            check_logic="len(response.split()) < 30"
        ),
        VoiceGuideline(
            id="turn_taking",
            name="Explicit Turn Yielding",
            description="End turns with a clear question or yield signal to prevent awkward silence.",
            check_logic="ends_with_question_mark(response)"
        ),
        VoiceGuideline(
            id="filler_words",
            name="Start With Fillers",
            description="Use 'Um', 'Ah', 'Well' at start of complex answers to mask latency.",
            check_logic="starts_with_filler(response)"
        ),
        VoiceGuideline(
            id="interruptibility",
            name="Allow Interruptions",
            description="Do not pack critical info in long blocks. Break it down.",
            check_logic="sentence_count(response) < 3"
        )
    ]

    def analyze_prompt(self, prompt_text: str) -> List[Dict[str, Any]]:
        """Analyze a prompt against voice best practices"""
        issues = []
        # Simple heuristic checks (placeholder logic)
        if len(prompt_text.split()) > 500: # Arbitrary threshold
            issues.append({
                "guideline": "conciseness",
                "severity": "medium",
                "message": "System prompt is very long, potentially increasing latency."
            })
        
        # Check for specific instructions in the prompt text
        if "wait related" not in prompt_text.lower() and "interruption" not in prompt_text.lower():
             issues.append({
                "guideline": "interruptibility",
                "severity": "low",
                "message": "Prompt lacks explicit instructions on handling user interruptions."
            })

        return issues

    def get_optimization_instructions(self) -> str:
        """Returns the system prompt injection for the Prompt Optimizer"""
        return """
        CRITICAL VOICE AI OPTIMIZATION RULES:
        1. BREVITY IS KING: The TTS engine needs short, punchy sentences.
        2. LATENCY MASKING: instruct the agent to use 'hmm', 'well', 'let me see' for complex queries.
        3. NATURAL FLOW: Avoid robotic lists. Use transitional phrases.
        4. CONFIRMATION: Verify numbers (phone, credit card) by repeating them in groups.
        5. NO MARKDOWN: Do not use bold/italics in the spoken response usually.
        """

voice_skill = VoiceSkill()
