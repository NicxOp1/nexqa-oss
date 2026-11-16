from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from typing import Optional, Dict, Any
from nexqa.integrations.retell_client import retell_client

console = Console()

def select_phone_number(agent_id: str, agent_name: str) -> Optional[str]:
    """
    Interactive CLI to select and assign a Retell phone number to an agent.
    
    1. List all numbers
    2. Show status (Assigned to whom? or Unassigned)
    3. User picks number
    4. If assigned, warning + confirm
    5. Call update_phone_number
    """
    console.print(f"\n[bold blue]Phone Number Assignment[/bold blue] for '{agent_name}' ({agent_id})")
    
    try:
        numbers = retell_client.list_phone_numbers()
    except Exception:
        console.print("[red]Failed to fetch phone numbers.[/red]")
        return None

    if not numbers:
        console.print("[yellow]No phone numbers found in Retell account.[/yellow]")
        return None

    # Sort numbers: Free ones first, then by number
    numbers.sort(key=lambda x: (x.get("agent_id") is not None, x.get("phone_number")))

    table = Table(title="Available Retell Numbers")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Phone Number", style="magenta")
    table.add_column("Current Status", style="green")
    table.add_column("Nickname", style="white")

    valid_choices = []
    
    for idx, num in enumerate(numbers):
        n_id = num.get("phone_number")
        current_agent = num.get("agent_id")
        nickname = num.get("nickname", "")
        
        status = "[dim]Unassigned[/dim]"
        if current_agent:
            if current_agent == agent_id:
                status = "[bold green]Already assigned to this agent[/bold green]"
            else:
                status = f"[yellow]Assigned to {current_agent}[/yellow]"
        
        table.add_row(str(idx + 1), n_id, status, nickname)
        valid_choices.append(str(idx + 1))

    console.print(table)
    console.print("[dim]Enter 's' to skip assignment.[/dim]")
    
    choice = Prompt.ask("Select number to assign", choices=valid_choices + ['s'], default='s')
    
    if choice == 's':
        console.print("[yellow]Skipping phone assignment.[/yellow]")
        return None
    
    selected_num = numbers[int(choice) - 1]
    phone_number = selected_num.get("phone_number")
    current_agent = selected_num.get("agent_id")
    
    # Warning if reassignment
    if current_agent and current_agent != agent_id:
        confirm = Confirm.ask(
            f"[red]WARNING: This number is currently assigned to {current_agent}.[/red]\n"
            "Are you sure you want to reassign it to the new agent?",
            default=False
        )
        if not confirm:
            console.print("[yellow]Assignment cancelled.[/yellow]")
            return None

    if current_agent == agent_id:
        console.print(f"[green]Number {phone_number} is already assigned to this agent.[/green]")
        return phone_number

    # Perform Update
    try:
        with console.status(f"Assigning {phone_number} to {agent_id}..."):
            retell_client.update_phone_number(phone_number, agent_id)
        console.print(f"[bold green]Successfully assigned {phone_number}![/bold green]")
        return phone_number
    except Exception as e:
        console.print(f"[red]Failed to assign number: {e}[/red]")
        return None
