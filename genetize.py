"""
NEXQA v1.0 — Genetize Agent Prompt

Converts a plain-text prompt into an XML-structured "Genome" prompt
using Claude's intelligence to identify Identity, Flow, Rules, etc.

Usage:
    python genetize.py <agent_id>
"""

import sys
import argparse
from nexqa.integrations.retell_client import retell_client
from nexqa.genetics.gene_parser import gene_parser
from nexqa.storage.logger import logger

def main():
    parser = argparse.ArgumentParser(description="Convert agent prompt to XML genes.")
    parser.add_argument("agent_id", help="Retell Agent ID to genetize")
    parser.add_argument("--force", action="store_true", help="Overwrite existing genes")
    
    args = parser.parse_args()
    agent_id = args.agent_id

    print(f"🧬 Genetizing Agent: {agent_id}")

    try:
        # 1. Fetch current prompt
        current_prompt = retell_client.get_current_prompt(agent_id)
        print(f"   Current Length: {len(current_prompt)} chars")

        # 2. Check if already genetized
        if "<gene" in current_prompt and not args.force:
            print("⚠️  Prompt already contains <gene> tags.")
            print("   Use --force to re-genetize (overwrite).")
            sys.exit(0)

        # 3. Auto-tag with Claude
        print("🤖 Invoking Claude to structure prompt (this may take 10-20s)...")
        tagged_prompt = gene_parser.auto_tag(current_prompt)
        
        # 4. Preview
        print("\n" + "="*40)
        print(tagged_prompt[:500] + "...\n[truncated]")
        print("="*40)
        print(f"   New Length: {len(tagged_prompt)} chars")

        # 5. Confirm
        confirm = input("\nApply this new structure to Retell Agent? (y/N): ")
        if confirm.lower() != 'y':
            print("❌ Aborted.")
            sys.exit(0)

        # 6. Update
        retell_client.update_prompt(agent_id, tagged_prompt)
        print("✅ Success! Agent prompt updated with Genes.")
        print("   You can now run 'nexqa optimize' with targeted mutations.")

    except Exception as e:
        logger.error(f"Genetization failed: {e}")
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
