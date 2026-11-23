"""
NEXQA v1.0 — Genetize Agent Prompt

Converts a plain-text prompt into an XML-structured "Genome" prompt
using Claude's intelligence to identify Identity, Flow, Rules, etc.

Usage:
    python genetize.py <agent_id>
"""

import sys as _sys

for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


import sys
import argparse
from nexqa.providers import get_provider, load_provider_settings
from nexqa.genetics.gene_parser import gene_parser
from nexqa.storage.logger import logger

def main():
    parser = argparse.ArgumentParser(description="Convert agent prompt to XML genes.")
    parser.add_argument("agent_id", help="ID of the agent to genetize on its platform")
    parser.add_argument("--force", action="store_true", help="Overwrite existing genes")
    parser.add_argument("--provider", default=None,
                        help="Voice platform (default: retell). See `nexqa providers`.")
    parser.add_argument("--spec", default=None,
                        help="Spec file to read provider / provider_config from")

    args = parser.parse_args()
    agent_id = args.agent_id
    spec_name, spec_config = load_provider_settings(args.spec)
    provider = get_provider(args.provider or spec_name,
                            spec_config if not args.provider else {})

    print(f"🧬 Genetizing Agent: {agent_id}")

    try:
        # 1. Fetch current prompt
        current_prompt = provider.get_prompt(agent_id)
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
        confirm = input(f"\nApply this new structure to the {provider.display_name} agent? (y/N): ")
        if confirm.lower() != 'y':
            print("❌ Aborted.")
            sys.exit(0)

        # 6. Update
        provider.update_prompt(agent_id, tagged_prompt)
        print("✅ Success! Agent prompt updated with Genes.")
        print("   You can now run 'nexqa optimize' with targeted mutations.")

    except Exception as e:
        logger.error(f"Genetization failed: {e}")
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
