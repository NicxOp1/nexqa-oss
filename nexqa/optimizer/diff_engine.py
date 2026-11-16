import difflib
from rich.console import Console
from rich.syntax import Syntax

console = Console()

class DiffEngine:
    """Visualizes differences between prompts."""
    
    def show_diff(self, old_text: str, new_text: str):
        """Print colored diff to console"""
        diff = difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile='Current Prompt',
            tofile='New Candidate',
            lineterm=''
        )
        
        diff_text = "\n".join(diff)
        if diff_text:
            syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=True)
            console.print(syntax)
        else:
            console.print("[green]No changes detected.[/green]")

diff_engine = DiffEngine()
