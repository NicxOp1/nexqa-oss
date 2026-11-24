import sys

# Windows consoles default to cp1252 and crash on the emoji in our output.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from pathlib import Path
from typing import Optional
import time
import json
import hashlib

from nexqa.storage.config import Config
from nexqa.storage.logger import logger
from nexqa.integrations.retell_client import retell_client
from nexqa.core.ingest import spec_ingestor
from nexqa.core.rule_compiler import rule_compiler
from nexqa.core.deterministic_validator import deterministic_validator
from nexqa.core.score_engine import score_engine
from nexqa.optimizer.prompt_optimizer import prompt_optimizer
from nexqa.optimizer.diff_engine import diff_engine
from nexqa.optimizer.linter import linter
from nexqa.reporting.html_report import html_reporter
from nexqa.models.scenario_models import SimulationResult

app = typer.Typer(help="NEXQA - Voice AI Prompt Engineering CLI")
console = Console(force_terminal=True)

@app.command()
def build(
    spec_path: Path = typer.Argument(..., help="Path to YAML agent specification")
):
    """
    Build and deploy a Retell LLM and its custom tools from a YAML specification.
    """
    console.print(f"[bold blue]NEXQA Builder[/bold blue] - Deploying from {spec_path}...")
    
    from nexqa.builder.agent_builder import builder
    
    with console.status("Provisioning Tools and LLM via Retell API..."):
        result = builder.build_from_spec(str(spec_path))
        
    if result:
        console.print("[green]✓ Deployment Successful![/green]")
        console.print(f"Agent/LLM ID: [bold]{result.get('llm_id', 'Unknown')}[/bold]")
        console.print("You can now assign this LLM to an agent in the Retell Dashboard.")
    else:
        console.print("[red]✗ Deployment Failed. Check logs for details.[/red]")


@app.command()
def providers():
    """List supported voice platforms and how mature each adapter is."""
    from rich.table import Table
    from nexqa.providers import list_providers

    table = Table(title="NEXQA providers")
    for col in ("provider", "platform", "maturity", "how tests run", "API key"):
        table.add_column(col)
    for row in list_providers():
        table.add_row(row["name"], row["display_name"], row["maturity"], row["test_mode"],
                      row["api_key_env"] or "-")
    console.print(table)
    console.print("[dim]Set `provider:` in your spec, or pass --provider to `nexqa run`.[/dim]")


def _run_with_engine(spec_path: Path, agent_id: str, provider_name: str, auto_apply: bool):
    """QA loop for any provider, through the shared engine."""
    import asyncio as _asyncio
    from nexqa.core.engine import engine
    from nexqa.providers import load_provider_settings, get_provider

    spec_name, spec_config = load_provider_settings(spec_path)
    provider = get_provider(provider_name, spec_config if provider_name == spec_name else {})
    console.print(f"[green]Provider: {provider.display_name} ({provider.maturity})[/green]")
    console.print(f"[dim]Tests: {provider.test_mode}[/dim]")

    if not auto_apply:
        def _confirm(old: str, new: str) -> bool:
            diff_engine.show_diff(old, new)
            return Confirm.ask(f"Apply this prompt update to the {provider.display_name} agent?")
        engine.confirm_update = _confirm

    result = _asyncio.run(engine.run_async(agent_id, spec_path, provider=provider))

    for it in result.iterations:
        console.print(f"Iteration {it.iteration}: score {it.avg_score:.2f}, "
                      f"{it.error_count} critical, action={it.action}")
        if it.evaluations:
            report_path = html_reporter.generate(it.evaluations, f"v{it.iteration}")
            console.print(f"  Report: [link={report_path}]{report_path}[/link]")
    color = "green" if result.success else "yellow"
    console.print(f"[bold {color}]Result: {result.action} (score {result.final_score:.2f})[/bold {color}]")
    if result.error:
        console.print(f"[red]{result.error}[/red]")
    cost = result.cost_metrics.get("total_cost_usd")
    if cost is not None:
        console.print(f"[dim]Estimated cost: ${cost}[/dim]")


@app.command()
def run(
    spec_path: Path = typer.Option(..., help="Path to QA Specification file"),
    agent_id: Optional[str] = typer.Option(None, help="ID of the agent to test on the platform"),
    provider: Optional[str] = typer.Option(
        None, help="Voice platform (retell, vapi, elevenlabs, ...). Default: the spec's "
                   "`provider:` key, else retell. See `nexqa providers`."),
    auto_apply: bool = typer.Option(
        False, "--auto-apply", help="Deploy prompt rewrites without asking (non-Retell runs)"),
):
    """
    Start the QA and Optimization Loop against a voice agent.

    Retell runs use Retell batch testing, exactly as before 0.3.0. Other
    platforms run through the shared engine and their provider adapter.
    """
    from nexqa.providers import load_provider_settings, normalize_name

    try:
        provider_name = normalize_name(provider) if provider else load_provider_settings(spec_path)[0]
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if provider_name != "retell":
        if not agent_id:
            console.print("[red]--agent-id is required for this provider.[/red]")
            raise typer.Exit(code=1)
        _run_with_engine(spec_path, agent_id, provider_name, auto_apply)
        return

    console.print("[bold blue]NEXQA v0.1 Starting...[/bold blue]")

    # 1. Select Agent
    response_engine = None
    if not agent_id:
        try:
            with console.status("Fetching agents..."):
                agents = retell_client.list_agents()
            
            if not agents:
                console.print("[red]No agents found.[/red]")
                return
            
            # Group agents by name
            agents_by_name = {}
            for agent in agents:
                name = agent.get('agent_name') or agent.get('name') or 'Unknown'
                if name not in agents_by_name:
                    agents_by_name[name] = []
                agents_by_name[name].append(agent)
            
            # Sort names
            unique_names = sorted(agents_by_name.keys())
            
            console.print("\nAvailable Agents:")
            for idx, name in enumerate(unique_names):
                count = len(agents_by_name[name])
                console.print(f"{idx+1}. {name} ({count} versions)")
            
            name_choice = Prompt.ask("Select Agent # to view versions", default="1")
            try:
                selected_name = unique_names[int(name_choice)-1]
            except (ValueError, IndexError):
                console.print("[red]Invalid selection.[/red]")
                return

            # Show versions for selected name
            console.print(f"\nVersions for '{selected_name}':")
            selected_agents = agents_by_name[selected_name]
            # Try to sort numerically if version is int, else string
            selected_agents.sort(key=lambda x: str(x.get('version', '0')), reverse=True) 

            for idx, agent in enumerate(selected_agents):
                ver = agent.get('version', '?')
                a_id = agent.get('agent_id', 'N/A')
                console.print(f"{idx+1}. v{ver} (ID: {a_id})")
            
            ver_choice = Prompt.ask("Select Version #", default="1")
            
            try:
                selected_agent = selected_agents[int(ver_choice)-1]
                agent_id = selected_agent['agent_id']
                # Capture Response Engine directly
                response_engine = selected_agent.get("response_engine")
                if not response_engine and selected_agent.get("llm_id"):
                    response_engine = {
                        "type": "retell-llm",
                        "llm_id": selected_agent.get("llm_id")
                    }
            except (ValueError, IndexError):
                console.print("[red]Invalid version selection.[/red]")
                return
        except Exception as e:
            console.print(f"[red]Error selecting agent: {e}[/red]")
            return
    else:
        if agent_id.startswith("llm_"):
            response_engine = {
                "type": "retell-llm",
                "llm_id": agent_id
            }
        else:
            # Fetch Agent details if provided via CLI
            try:
                agent_details = retell_client.get_agent(agent_id)
                response_engine = agent_details.get("response_engine")
                if not response_engine and agent_details.get("llm_id"):
                    response_engine = {
                        "type": "retell-llm",
                        "llm_id": agent_details.get("llm_id")
                    }
            except Exception as e:
                console.print(f"[yellow]Warning: Could not fetch agent details to pre-cache response engine: {e}[/yellow]")

    console.print(f"[green]Selected Agent: {agent_id}[/green]")

    # ── Cache helpers ──────────────────────────────────────────────────────────
    spec_content = Path(spec_path).read_text(encoding="utf-8")
    spec_hash = hashlib.md5(spec_content.encode()).hexdigest()[:12]
    cache_file = Config.CACHE_DIR / f"run_{spec_hash}_{agent_id[:12]}.json"

    def _load_cache():
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text())
            except Exception:
                pass
        return None

    def _save_cache(data: dict):
        Config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data, indent=2))

    cached = _load_cache()

    # ── 2. Ingest Spec (use cache if available) ──────────────────────────────
    # Always load raw YAML for tool_mocks (needed even on cache hit)
    try:
        import yaml as _yaml
        _raw_spec_yaml = _yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
        spec_global_mocks: dict = _raw_spec_yaml.get("tool_mocks", {}).get("default", {})
        _scenario_mock_overrides: dict = _raw_spec_yaml.get("tool_mocks", {}).get("scenarios", {})
    except Exception as _e:
        logger.warning(f"Could not load tool_mocks from YAML: {_e}")
        spec_global_mocks = {}
        _scenario_mock_overrides = {}

    if cached and "compiled_spec" in cached:
        console.print(
            f"[green]✓ Cache hit[/green] [dim]({cache_file.name})[/dim] — "
            f"restoring spec from cache, skipping Claude + Retell registration."
        )
        test_case_ids = cached["test_case_ids"]
        # Restore CompiledSpec from cache (no Claude needed)
        try:
            from nexqa.models.rule_models import CompiledSpec
            spec = CompiledSpec(**cached["compiled_spec"])
            # Re-apply scenario mock overrides from YAML
            for _sc in spec.scenarios:
                if _sc.name in _scenario_mock_overrides:
                    _sc.tool_mocks.update(_scenario_mock_overrides[_sc.name])
            rules = rule_compiler.compile(spec)
            console.print(f"[dim]Restored {len(spec.scenarios)} scenarios and {len(spec.hard_rules)} rules from cache.[/dim]")
        except Exception as e:
            console.print(f"[yellow]Could not restore rules from cache ({e}). Rules will be skipped.[/yellow]")
            spec = None
            rules = None
    else:
        console.print(f"\n[bold]Ingesting Spec from {spec_path}...[/bold]")
        try:
            spec = spec_ingestor.ingest(spec_path)
            rules = rule_compiler.compile(spec)
            console.print(f"[green]Successfully ingested {len(spec.scenarios)} scenarios and {len(spec.hard_rules)} rules.[/green]")
        except Exception as e:
            console.print(f"[red]Ingestion Failed: {e}[/red]")
            return

        # ── 3. Register Test Cases in Retell ──────────────────────────────────
        test_case_ids = []

        # Load global tool_mocks from spec YAML (default mocks applied to all scenarios)
        try:
            import yaml as _yaml
            _raw_spec = _yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
            spec_global_mocks: dict = _raw_spec.get("tool_mocks", {}).get("default", {})
            _scenario_mock_overrides: dict = _raw_spec.get("tool_mocks", {}).get("scenarios", {})
        except Exception as _e:
            logger.warning(f"Could not load tool_mocks from spec YAML: {_e}")
            spec_global_mocks = {}
            _scenario_mock_overrides = {}

        # Merge per-scenario overrides into each scenario's tool_mocks
        for _sc in spec.scenarios:
            if _sc.name in _scenario_mock_overrides:
                _sc.tool_mocks.update(_scenario_mock_overrides[_sc.name])

        with console.status("Registering test cases with Retell..."):
            llm_id = response_engine.get("llm_id") if response_engine else None
            if not llm_id:
                console.print("[red]Cannot register test cases: no llm_id found for agent.[/red]")
                return

            for scenario in spec.scenarios:
                try:
                    # Retell's user_prompt is a BEHAVIORAL description for the simulated user
                    user_prompt = scenario.user_prompt


                    # Build metrics: Retell requires at least 1 non-empty free-text criterion
                    metrics = []
                    if scenario.expected_outcome:
                        metrics.append(scenario.expected_outcome)
                    for checkpoint in scenario.critical_checkpoints:
                        metrics.append(checkpoint)
                    if not metrics:
                        metrics = [f"Agent handles '{scenario.name}' correctly and professionally."]

                    # Build tool_mocks: start from scenario-level, fall back to global defaults
                    # This ensures simulations use ideal responses regardless of webhook status
                    effective_mocks = dict(spec_global_mocks)  # global defaults
                    effective_mocks.update(scenario.tool_mocks)  # scenario overrides

                    tc_id = retell_client.create_test_case_definition(
                        name=scenario.name,
                        user_prompt=user_prompt,
                        llm_id=llm_id,
                        metrics=metrics,
                        tool_mocks=effective_mocks if effective_mocks else None,
                    )

                    if tc_id:
                        test_case_ids.append(tc_id)
                        console.print(f"  [green][OK][/green] Registered: {scenario.name}")
                except Exception as e:
                    console.print(f"  [yellow][WARN] Skipping '{scenario.name}': {e}[/yellow]")

        if not test_case_ids:
            console.print("[red]No test cases could be registered. Exiting.[/red]")
            return

        # Save to cache: include compiled spec so next run restores without Claude
        _save_cache({
            "test_case_ids": test_case_ids,
            "spec_hash": spec_hash,
            "compiled_spec": spec.model_dump(),
        })
        console.print(f"[dim]Cache saved → {cache_file.name}[/dim]")

    current_iteration = 0
    max_iterations = Config.MAX_OPTIMIZATION_ITERATIONS
    
    while current_iteration <= max_iterations:
        console.print(f"\n[bold magenta]--- Iteration {current_iteration} ---[/bold magenta]")
        
        # 4. Run Batch Simulation
        try:
            if not response_engine:
                raise ValueError("Response engine not found for agent.")
            batch_id = retell_client.create_batch_test(test_case_ids, response_engine)
            console.print(f"Batch Test Initiated: {batch_id}")
        except Exception as e:
            console.print(f"[red]Failed to start batch test: {e}[/red]")
            break

        # 5. Poll for Completion
        batch_summary = {}
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            task = progress.add_task("Running simulations...", total=None)

            while True:
                time.sleep(8)  # Poll interval
                batch_status = retell_client.get_batch_test(batch_id)
                status = batch_status.get("status")
                total = batch_status.get("total_count", 0)
                done = batch_status.get("pass_count", 0) + batch_status.get("fail_count", 0) + batch_status.get("error_count", 0)
                progress.update(task, description=f"Running simulations... ({done}/{total} done)")

                if status == "complete":
                    batch_summary = batch_status
                    progress.update(task, completed=True)
                    break
                elif status in ("failed", "error"):
                    console.print("[red]Batch test failed on Retell side.[/red]")
                    break

        # 6. Fetch individual test run results via list-test-runs
        console.print("\n[bold]Fetching individual results...[/bold]")
        try:
            completed_results = retell_client.list_test_runs(batch_id)
        except Exception as e:
            console.print(f"[red]Could not retrieve test run results: {e}[/red]")
            completed_results = []

        # Display summary
        pass_c = batch_summary.get("pass_count", 0)
        fail_c = batch_summary.get("fail_count", 0)
        err_c = batch_summary.get("error_count", 0)
        total_c = batch_summary.get("total_count", len(completed_results))
        console.print(f"\n[bold]Results: [green]{pass_c} pass[/green] / [red]{fail_c} fail[/red] / [yellow]{err_c} error[/yellow] out of {total_c}[/bold]")

        for run in completed_results:
            name = run.get("test_case_definition_snapshot", {}).get("name", run.get("test_case_definition_id", "?"))
            run_status = run.get("status", "?")
            explanation = run.get("result_explanation", "")
            icon = {"pass": "[green][OK][/green]", "fail": "[red][FAIL][/red]", "error": "[yellow][ERR][/yellow]"}.get(run_status, "?")
            console.print(f"  {icon} [{run_status.upper()}] {name}")
            if explanation:
                console.print(f"      [dim]{explanation[:200]}[/dim]")

        if not completed_results:
            console.print("[red]No results returned.[/red]")
            break

        # 6. Evaluate & Score
        evaluations = []
        for res in completed_results:
            # Map Retell result back to Scenario ID
            # Assuming 'test_case_definition_id' is present in result
            # We match it to our scenarios list? Or just process what we have.
            
            # Simple simulation result mapping
            sim_result = SimulationResult(
                scenario_id=res.get("test_case_definition_id", "unknown"),
                transcript=res.get("transcript", ""),
                tool_calls=[], # Extract if available
                metadata=res,
                status="completed"
            )
            
            det_res = deterministic_validator.validate(sim_result, rules) if rules else None
            eval_res = score_engine.evaluate(sim_result.scenario_id, sim_result.transcript, det_res)
            evaluations.append(eval_res)
        
        # 7. Report & Decide
        avg_score = sum(r.overall_score for r in evaluations) / len(evaluations) if evaluations else 0
        console.print(f"\n[bold]Average Score: {avg_score:.2f}[/bold]")
        
        report_path = html_reporter.generate(evaluations, f"v{current_iteration}")
        console.print(f"Report generated: [link={report_path}]{report_path}[/link]")
        
        if avg_score >= Config.DEFAULT_THRESHOLD:
            console.print("[bold green]Threshold met! Deployment Candidate Ready.[/bold green]")
            break
            
        if current_iteration == max_iterations:
            console.print("[red]Max iterations reached. Stopping.[/red]")
            break
            
        # 8. Optimization Loop
        if Confirm.ask("Score below threshold. Attempt optimization?"):
            # Fetch current prompt correctly via helper
            current_prompt = retell_client.get_current_prompt(agent_id)
            
            all_issues = []
            for r in evaluations:
                all_issues.extend(r.semantic_issues)
            
            console.print("[cyan]Consulting Voice AI Expert & Claude...[/cyan]")
            new_prompt = prompt_optimizer.Optimize(current_prompt, all_issues, spec.raw_text)
            
            if linter.lint(current_prompt, new_prompt):
                diff_engine.show_diff(current_prompt, new_prompt)
                
                if Confirm.ask("Apply this prompt update to Retell Agent?"):
                    retell_client.update_prompt(agent_id, new_prompt)
                    console.print("[green]Agent updated. Starting next iteration...[/green]")
                    current_iteration += 1
                else:
                    console.print("Update rejected.")
                    break
            else:
                console.print("[red]Linting failed. Optimization unsafe.[/red]")
                break
        else:
            break


@app.command()
def create(
    spec_path: Path = typer.Option(..., help="Path to QA Specification file"),
    deploy: bool = typer.Option(False, "--deploy", "-d", help="Create live Retell agent"),
    setup_airtable: bool = typer.Option(False, "--setup-airtable", help="Run Airtable Auto-Setup"),
    out_dir: Path = typer.Option(
        Path("build"), "--out", "-o", help="Where to write the generated prompt and tools"
    ),
):
    """
    Create a new agent from a YAML specification.
    
    1. Parses the YAML spec.
    2. Builds the Prompt and Tools.
    3. (Optional) Deploys to Retell AI as a new Agent.
    4. (Optional) Assigns a phone number.
    5. (Optional) Sets up Airtable registry.
    """
    import yaml
    import asyncio
    from nexqa.genetics.prompt_builder import PromptBuilder
    from nexqa.genetics.tool_builder import ToolBuilder
    
    if not spec_path.exists():
        console.print(f"[red]Spec file not found: {spec_path}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold blue]NEXQA Create: Processing {spec_path.name}...[/bold blue]")

    # 1. Parse Spec
    try:
        raw_spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"[red]Failed to parse YAML: {e}[/red]")
        raise typer.Exit(code=1)

    agent_name = raw_spec.get("agent_name", "Untitled Agent")
    voice_id = raw_spec.get("voice_id", "11labs-Adrian")  # Default or extract
    
    # 2. Build Prompt & Tools
    try:
        with console.status("Building prompt & tools..."):
            pb = PromptBuilder()
            gene_set = pb.build(spec_path)
            prompt_text = pb.build_prompt_text(gene_set)
            
            tb = ToolBuilder()
            
            # Initially build tools without webhook ID since we don't have agent ID yet
            tools = tb.build_from_spec(raw_spec, webhook_url="https://placeholder.com")
            
            console.print(f"[green]✓ Built prompt ({len(prompt_text)} chars) and {len(tools)} tools.[/green]")
    except Exception as e:
        console.print(f"[red]Build failed: {e}[/red]")
        raise typer.Exit(code=1)

    slug = "".join(c if c.isalnum() else "_" for c in agent_name.lower()).strip("_") or "agent"
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = out_dir / f"{slug}_prompt.txt"
    tools_file = out_dir / f"{slug}_tools.json"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    tools_file.write_text(json.dumps(tools, indent=2), encoding="utf-8")
    console.print(f"[green]✓ Wrote {prompt_file} and {tools_file}[/green]")
    if not deploy:
        console.print("[dim]Add --deploy to create this agent in Retell.[/dim]")

    # 3. Deploy
    if deploy:
        if Confirm.ask(f"Deploy '{agent_name}' to Retell AI?"):
            try:
                with console.status("Creating Retell Agent..."):
                    
                    full_resp = retell_client.create_full_agent(
                        general_prompt=prompt_text,
                        voice_id=voice_id,
                        agent_name=agent_name,
                        general_tools=tools, # Pass tools initially
                        begin_message=raw_spec.get("begin_message", "Hello!"),
                    )
                    
                    agent_id = full_resp["agent_id"]
                    llm_id = full_resp["llm_id"]
                    
                    console.print(f"[bold green]✓ Deployed Agent: {agent_id}[/bold green]")
                    console.print(f"[dim]LLM ID: {llm_id}[/dim]")

                    # 3b. Update Webhooks with Agent ID
                    real_webhook_url = f"{Config.WEBHOOK_BASE_URL.rstrip('/')}/webhook/{agent_id}"
                    
                    # Re-build tools with this URL
                    updated_tools = tb.build_from_spec(raw_spec, webhook_url=real_webhook_url)
                    
                    # Update the LLM with new tools
                    retell_client.update_retell_llm(
                        llm_id=llm_id,
                        general_prompt=prompt_text,
                        general_tools=updated_tools
                    )

                    # Update Agent with Webhook for events (Analysis)
                    retell_client.update_agent(
                        agent_id=agent_id,
                        webhook_url=real_webhook_url,
                        webhook_events=["call_analyzed", "call_ended", "call_started"]
                    )
                    console.print("[green]✓ Updated agent webhooks (Analysis enabled)[/green]")
                    console.print(f"[green]✓ Updated tools with webhook URL: {real_webhook_url}[/green]")

                    # 4. Phone Selection
                    from nexqa.phone_selector import select_phone_number
                    phone = select_phone_number(agent_id, agent_name)
                    
                    # 5. Register in Webhook Server (Airtable)
                    if setup_airtable or Confirm.ask("Register agent in Airtable Webhook Registry?"):
                        from webhook_server.models import AgentRegistry, ConnectorType, FunctionConfig
                        from webhook_server.registry import register_agent
                        
                        # Extract integrations from spec
                        integrations = raw_spec.get("integrations", {})
                        functions = {}
                        
                        for func_name, integ_cfg in integrations.items():
                            conn_type = integ_cfg.get("connector")
                            func_conf = integ_cfg.get("config", {})
                            if conn_type:
                                functions[func_name] = FunctionConfig(
                                    connector=ConnectorType(conn_type),
                                    config=func_conf
                                )
                        
                        reg_entry = AgentRegistry(
                            agent_id=agent_id,
                            agent_name=agent_name,
                            company_name=raw_spec.get("company_name", "Unknown"),
                            phone_number=phone or "",
                            functions=functions,
                            active=True
                        )
                        
                        success = asyncio.run(register_agent(reg_entry))
                        if success:
                            console.print("[green]✓ Agent registered in Airtable registry.[/green]")
                        else:
                            console.print("[red]✗ Failed to register in Airtable.[/red]")

            except Exception as e:
                import traceback
                error_msg = traceback.format_exc()
                Config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
                tb_file = Config.LOGS_DIR / "last_traceback.txt"
                tb_file.write_text(error_msg, encoding="utf-8")
                console.print(f"[red]Deployment failed: {e}[/red]")
                console.print(f"[dim]See {tb_file} for details[/dim]")
                raise typer.Exit(code=1)

    # Airtable Auto-Setup Standalone
    if setup_airtable and not deploy:
        console.print("Running Airtable Setup...")
        from webhook_server.setup.airtable_setup import main as setup_main
        asyncio.run(setup_main())


if __name__ == "__main__":
    app()
