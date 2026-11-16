from typing import List
from nexqa.integrations.claude_client import claude_client
from nexqa.models.scenario_models import SemanticIssue
from nexqa.storage.logger import logger
from nexqa.optimizer.voice_skill import voice_skill

class PromptOptimizer:
    """Uses Claude to improve prompts based on evaluation feedback."""
    
    def Optimize(self, current_prompt: str, issues: List[SemanticIssue], rule_context: str) -> str:
        
        voice_best_practices = voice_skill.get_optimization_instructions()
        
        system_prompt = f"""
        You are an elite Voice AI Prompt Engineer.
        Your goal is to fix the issues identified in the simulation without breaking existing functionality.
        
        {voice_best_practices}
        
        Current Rules Context:
        {rule_context}
        
        Output only the new optimized prompt. No explanation.
        """
        
        issues_text = "\n".join([f"- {i.section} ({i.severity}): {i.description}" for i in issues])
        
        user_msg = f"""
        Current Prompt:
        {current_prompt}
        
        Identified Issues:
        {issues_text}
        
        Please rewrite the prompt to address these issues while adhering to Voice AI best practices.
        """
        
        logger.info("Optimizing prompt with Claude...")
        new_prompt = claude_client.complete(system_prompt, user_msg)
        return new_prompt.strip()

prompt_optimizer = PromptOptimizer()
