import sys
import argparse
import atexit
import signal
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file before any other imports
load_dotenv()

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.syntax import Syntax
from rich.live import Live
from . import k8s_actions, host_actions, watcher, alerter

def signal_handler(sig, frame):
    """Handles termination signals for graceful shutdown and logging."""
    print(f"\nSignal {signal.Signals(sig).name} received. Shutting down gracefully...")
    alerter.log_program_termination()
    sys.exit(0)

def show_menu(console):
    """Displays the main menu."""
    console.print("\n[bold cyan]Unified Monitor[/bold cyan]")
    console.print("---[ Kubernetes ]---")
    console.print("1. Dashboard")
    console.print("2. View Node Information")
    console.print("3. List All Namespaces")
    console.print("4. View Services")
    console.print("5. Stream Cluster Events")
    console.print("6. View Resource Quotas")
    console.print("7. View Pod Status & Usage")
    console.print("8. View Deployment Status & Usage")
    console.print("9. View Pod Logs")
    console.print("10. Open Interactive Pod Shell")
    console.print("11. Scale a Deployment")
    console.print("12. Edit a Deployment")
    console.print("13. View Persistent Volumes")
    console.print("14. View Persistent Volume Claims")
    console.print("15. View ConfigMaps")
    console.print("16. View Secrets")
    console.print("17. View Resource YAML")
    console.print("18. Describe K8s Resource")
    console.print("---[ Host Monitoring ]---")
    console.print("19. View Host Resource Usage")
    console.print("20. View Process Explorer")
    console.print("21. View Docker Containers")
    console.print("22. View Host System Logs")
    console.print("23. View Network Stats")
    console.print("---[ System ]---")
    console.print("24. Exit")
    return Prompt.ask("[bold]Choose an option[/bold]", choices=[str(i) for i in range(1, 25)], default="1")

from rich.layout import Layout
from rich.live import Live
import time

def generate_dashboard_layout(core_v1_api, apps_v1_api, custom_objects_api):
    """Generates the layout for the dashboard."""
    layout = Layout()

    layout.split(
        Layout(name="header", size=1),
        Layout(ratio=1, name="main"),
        Layout(size=1, name="footer")
    )

    layout["main"].split_row(Layout(name="left", ratio=2), Layout(name="right", ratio=3))
    layout["left"].split_column(Layout(name="host_status"), Layout(name="k8s_status"))
    layout["right"].split_column(Layout(name="workload_summary"), Layout(name="events"))
    
    # Header and Footer
    layout["header"].update("[bold cyan]Unified Monitor Dashboard[/bold cyan]")
    layout["footer"].update("[dim]Press Ctrl+C to exit. For more details, use other menu options.[/dim]")

    # Host Status
    try:
        util = host_actions.get_resource_utilization()
        mem = util['memory']
        disk = util['disk_root']
        host_table = Table(title="Host Status", show_header=False, box=None)
        host_table.add_row("CPU:", f"{util['cpu_percent']:.1f}%")
        host_table.add_row("Memory:", f"{mem.percent:.1f}% ({mem.used/1024**3:.2f}GiB / {mem.total/1024**3:.2f}GiB)")
        host_table.add_row("Disk (/):", f"{disk.percent:.1f}% ({disk.used/1024**3:.2f}GiB / {disk.total/1024**3:.2f}GiB)")
        layout["host_status"].update(Panel(host_table, border_style="green"))
    except Exception as e:
        layout["host_status"].update(Panel(f"[red]Error: {e}[/red]", border_style="red"))

    # K8s Node Status
    try:
        nodes = k8s_actions.get_node_info(core_v1_api)
        node_table = Table(title="Cluster Nodes", box=None)
        node_table.add_column("Name")
        node_table.add_column("Status")
        node_table.add_column("Roles")
        for node in nodes:
            node_table.add_row(node['name'], node['status'], node['roles'])
        layout["k8s_status"].update(Panel(node_table, border_style="blue"))
    except Exception as e:
        layout["k8s_status"].update(Panel(f"[red]Error: {e}[/red]", border_style="red"))

    # Workload Summary
    try:
        pods, _ = k8s_actions.get_pod_status(core_v1_api, custom_objects_api, "all")
        deployments, _ = k8s_actions.get_deployment_status(core_v1_api, apps_v1_api, custom_objects_api, "all")

        # --- Deployments Table ---
        dep_table = Table(title="Deployments", show_header=True, box=None)
        dep_table.add_column("Name", style="cyan")
        dep_table.add_column("Replicas", style="green")
        dep_table.add_column("CPU (cores)", style="magenta", justify="right")
        dep_table.add_column("Memory (MiB)", style="red", justify="right")
        
        if deployments:
            # Sort deployments by name and limit to 10
            sorted_deps = sorted(deployments, key=lambda d: d['name'])
            for dep in sorted_deps[:10]:
                dep_table.add_row(
                    dep['name'],
                    f"{dep['ready_replicas'] or 0}/{dep['replicas'] or 0}",
                    f"{dep['cpu'] / 1000:.3f}",
                    f"{dep['memory'] / 1024:.2f}"
                )
            if len(deployments) > 10:
                dep_table.add_row(f"[dim]...and {len(deployments) - 10} more[/dim]", "", "", "")

        # --- Pods Table (Top 10 by Memory) ---
        pod_table = Table(title="Top 10 Pods by Memory", show_header=True, box=None)
        pod_table.add_column("Name", style="cyan", overflow="elide")
        pod_table.add_column("Status", style="magenta")
        pod_table.add_column("CPU", style="yellow", justify="right")
        pod_table.add_column("Memory", style="red", justify="right")

        if pods:
            # Sort pods by memory usage, descending
            sorted_pods = sorted(pods, key=lambda p: k8s_actions.parse_memory_value(p.get('memory', '0')), reverse=True)
            for pod in sorted_pods[:10]:
                pod_table.add_row(
                    pod['name'],
                    pod['status'],
                    pod['cpu'],
                    pod['memory']
                )
            if len(pods) > 10:
                pod_table.add_row(f"[dim]...and {len(pods) - 10} more[/dim]", "", "", "")

        workload_layout = Layout()
        workload_layout.split_column(Layout(dep_table), Layout(pod_table))
        layout["workload_summary"].update(Panel(workload_layout, title="Workload Summary", border_style="magenta"))
    except Exception as e:
        layout["workload_summary"].update(Panel(f"[red]Error: {e}[/red]", border_style="red"))

    # Recent Events
    try:
        events, error = k8s_actions.get_events(core_v1_api, limit=10)
        if error:
            layout["events"].update(Panel(f"[red]Error: {error}[/red]", border_style="red"))
        else:
            event_table = Table(title="Recent Cluster Events", box=None)
            event_table.add_column("Time", style="cyan")
            event_table.add_column("Type", style="magenta")
            event_table.add_column("Reason", style="yellow")
            event_table.add_column("Object", style="blue")
            event_table.add_column("Message", style="green")
            for event in events:
                event_table.add_row(event['last_seen'], event['type'], event['reason'], event['object'], event['message'])
            layout["events"].update(Panel(event_table, border_style="yellow"))
    except Exception as e:
        layout["events"].update(Panel(f"[red]Error: {e}[/red]", border_style="red"))

    return layout

def display_dashboard(console, core_v1_api, apps_v1_api, custom_objects_api):
    """Displays a live-updating dashboard."""
    try:
        with Live(generate_dashboard_layout(core_v1_api, apps_v1_api, custom_objects_api), console=console, screen=True, refresh_per_second=4) as live:
            while True:
                time.sleep(2)
                live.update(generate_dashboard_layout(core_v1_api, apps_v1_api, custom_objects_api))
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped. Returning to main menu.[/yellow]")
        return

def open_pod_shell(console, core_v1_api):
    """Handles opening an interactive shell in a pod."""
    try:
        console.print("\n[bold]Opening Interactive Pod Shell...[/bold]")
        console.print("[yellow]Note: This feature is Unix-specific. Use 'exit' or Ctrl+D to leave the shell.[/yellow]")
        
        namespace = Prompt.ask("Enter namespace", default="default")
        pod_name = Prompt.ask("Enter pod name")
        
        # Optional: Ask for container name if multiple containers exist
        # For simplicity, we'll try to exec into the first container or default shell
        # A more robust solution would list containers and let the user choose.
        container_name = Prompt.ask("Enter container name (optional)", default="")
        
        if not pod_name:
            console.print("[red]Pod name cannot be empty.[/red]")
            return

        console.print(f"[green]Connecting to shell in pod '{pod_name}' in namespace '{namespace}'...[/green]")
        console.print("[yellow]Press Ctrl+C to return to main menu if connection fails.[/yellow]")

        # Temporarily disable rich's terminal handling to allow raw mode
        console.file = sys.stdout # Direct output to stdout
        console.is_terminal = True # Ensure rich thinks it's a terminal

        k8s_actions.exec_shell_in_pod(core_v1_api, namespace, pod_name, container_name if container_name else None)
        
        # Re-enable rich's terminal handling
        console.file = sys.stdout
        console.is_terminal = True

    except KeyboardInterrupt:
        console.print("\n[yellow]Shell connection interrupted. Returning to main menu.[/yellow]")
        return
    except Exception as e:
        console.print(f"\n[bold red]Error opening pod shell: {e}[/bold red]")
        return


def display_event_stream(console, core_v1_api):
    """Displays a live stream of cluster events."""
    console.print("\n[bold]Starting real-time event stream... (Press Ctrl+C to stop)[/bold]")
    
    table = Table(title="Live Cluster Events")
    table.add_column("LAST SEEN", style="cyan", no_wrap=True)
    table.add_column("TYPE", style="magenta")
    table.add_column("REASON", style="yellow")
    table.add_column("OBJECT", style="blue")
    table.add_column("MESSAGE", style="green")

    try:
        with Live(table, refresh_per_second=4, screen=True, console=console) as live:
            for event in k8s_actions.stream_events(core_v1_api):
                if "error" in event:
                    live.console.print(f"[bold red]Error in stream: {event['error']}[/bold red]")
                    break
                
                # Add event to table, ensuring we don't grow it indefinitely
                if len(table.rows) > 20:
                    table.rows.pop(0)

                table.add_row(
                    event['last_seen'],
                    event['type'],
                    event['reason'],
                    event['object'],
                    event['message']
                )
    except KeyboardInterrupt:
        # The 'with' context will handle stopping the live display
        pass
    finally:
        console.print("\n[yellow]Event stream stopped. Returning to main menu.[/yellow]")
        return

def display_services(console, core_v1_api):
    """Handles the logic for displaying service information."""
    try:
        namespace_input = Prompt.ask("Enter namespace ('all' for all, press Enter for 'default')")
        namespace = namespace_input.strip() or "default"
        
        console.print(f"\n[bold]Fetching services in namespace: {namespace}...[/bold]")
        
        services, error = k8s_actions.get_services(core_v1_api, namespace)
        
        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
            return
        if not services:
            console.print(f"[yellow]No services found in namespace '{namespace}'.[/yellow]")
            return

        table = Table(title=f"Services in Namespace: {namespace}")
        table.add_column("Name", style="cyan")
        table.add_column("Namespace", style="blue")
        table.add_column("Type", style="yellow")
        table.add_column("Cluster IP", style="magenta")
        table.add_column("External IP", style="green")
        table.add_column("Ports", style="red")

        for svc in services:
            table.add_row(svc['name'], svc['namespace'], svc['type'], svc['cluster_ip'], svc['external_ip'], svc['ports'])
        
        console.print(table)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return

def display_resource_yaml(console, core_v1_api, apps_v1_api):
    """Handles the interactive selection and display of a resource's YAML."""
    try:
        console.print("\n---[ Select a Resource Type to View YAML ]---")
        resource_type = Prompt.ask("Choose resource type", choices=["Pod", "Deployment", "Node", "Service"], default="Pod")

        yaml_str, error = None, None

        if resource_type == "Node":
            name = Prompt.ask("Enter Node name")
            if name:
                yaml_str, error = k8s_actions.get_node_yaml(core_v1_api, name)
        else: # Pod, Deployment, or Service
            namespace = Prompt.ask("Enter namespace", default="default")
            name = Prompt.ask(f"Enter {resource_type} name")
            if namespace and name:
                if resource_type == "Pod":
                    yaml_str, error = k8s_actions.get_pod_yaml(core_v1_api, namespace, name)
                elif resource_type == "Deployment":
                    yaml_str, error = k8s_actions.get_deployment_yaml(apps_v1_api, namespace, name)
                elif resource_type == "Service":
                    # We need a get_service_yaml function
                    # For now, let's reuse the generic helper
                    yaml_str, error = k8s_actions._get_resource_as_yaml(core_v1_api.read_namespaced_service, name=name, namespace=namespace)


        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
        elif yaml_str:
            syntax = Syntax(yaml_str, "yaml", theme="dracula", line_numbers=True)
            console.print(Panel(syntax, title=f"YAML for {resource_type}: {name}", border_style="green"))
        else:
            console.print("[yellow]No name entered or operation cancelled.[/yellow]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return


import plotext as plt
from collections import deque

def display_configmaps(console, core_v1_api):
    """Displays a list of ConfigMaps and allows viewing their data."""
    try:
        namespace = Prompt.ask("Enter namespace ('all' for all, press Enter for 'default')")
        namespace = namespace.strip() or "default"
        
        console.print(f"\n[bold]Fetching ConfigMaps in namespace: {namespace}...[/bold]")
        
        configmaps, error = k8s_actions.get_configmaps(core_v1_api, namespace)
        
        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
            return
        if not configmaps:
            console.print(f"[yellow]No ConfigMaps found in namespace '{namespace}'.[/yellow]")
            return

        table = Table(title=f"ConfigMaps in Namespace: {namespace}")
        table.add_column("Name", style="cyan")
        table.add_column("Data Keys", style="blue")

        for cm in configmaps:
            table.add_row(cm['name'], ", ".join(cm['data'].keys()) if cm['data'] else "")
        
        console.print(table)

        if Confirm.ask("\n[bold]View data from a specific ConfigMap?[/bold]"):
            cm_name = Prompt.ask("Enter ConfigMap name")
            for cm in configmaps:
                if cm['name'] == cm_name:
                    console.print(Panel(yaml.dump(cm['data'], sort_keys=False), title=f"Data for ConfigMap: {cm_name}", border_style="green"))
                    break
            else:
                console.print(f"[red]ConfigMap '{cm_name}' not found.[/red]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return

def display_secrets(console, core_v1_api):
    """Displays a list of Secrets and allows viewing their decoded data."""
    try:
        namespace = Prompt.ask("Enter namespace ('all' for all, press Enter for 'default')")
        namespace = namespace.strip() or "default"
        
        console.print(f"\n[bold]Fetching Secrets in namespace: {namespace}...[/bold]")
        
        secrets, error = k8s_actions.get_secrets(core_v1_api, namespace)
        
        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
            return
        if not secrets:
            console.print(f"[yellow]No Secrets found in namespace '{namespace}'.[/yellow]")
            return

        table = Table(title=f"Secrets in Namespace: {namespace}")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="blue")

        for s in secrets:
            table.add_row(s['name'], s['type'])
        
        console.print(table)

        if Confirm.ask("\n[bold yellow]View data from a specific Secret? (WARNING: Data will be decoded and displayed in plain text)[/bold yellow]"):
            secret_name = Prompt.ask("Enter Secret name")
            for s in secrets:
                if s['name'] == secret_name:
                    console.print(Panel(yaml.dump(s['data'], sort_keys=False), title=f"Decoded Data for Secret: {secret_name}", border_style="red"))
                    break
            else:
                console.print(f"[red]Secret '{secret_name}' not found.[/red]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return

def display_persistent_volumes(console, core_v1_api):
    """Displays a list of Persistent Volumes."""
    console.print("\n[bold]Fetching Persistent Volumes...[/bold]")
    try:
        pvs, error = k8s_actions.get_persistent_volumes(core_v1_api)
        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
            return
        if not pvs:
            console.print("[yellow]No Persistent Volumes found.[/yellow]")
            return

        table = Table(title="Persistent Volumes")
        table.add_column("Name", style="cyan")
        table.add_column("Capacity", style="magenta")
        table.add_column("Access Modes", style="blue")
        table.add_column("Status", style="green")
        table.add_column("Claim", style="yellow")
        table.add_column("Storage Class", style="red")

        for pv in pvs:
            table.add_row(pv['name'], pv['capacity'], pv['access_modes'], pv['status'], pv['claim'], pv['storage_class'])
        
        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Error fetching Persistent Volumes: {e}[/bold red]")

def display_persistent_volume_claims(console, core_v1_api):
    """Displays a list of Persistent Volume Claims."""
    try:
        namespace = Prompt.ask("Enter namespace ('all' for all, press Enter for 'default')")
        namespace = namespace.strip() or "default"
        
        console.print(f"\n[bold]Fetching Persistent Volume Claims in namespace: {namespace}...[/bold]")
        
        pvcs, error = k8s_actions.get_persistent_volume_claims(core_v1_api, namespace)
        
        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
            return
        if not pvcs:
            console.print(f"[yellow]No Persistent Volume Claims found in namespace '{namespace}'.[/yellow]")
            return

        table = Table(title=f"Persistent Volume Claims in Namespace: {namespace}")
        table.add_column("Name", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Volume", style="blue")
        table.add_column("Capacity", style="green")
        table.add_column("Access Modes", style="yellow")
        table.add_column("Storage Class", style="red")

        for pvc in pvcs:
            table.add_row(pvc['name'], pvc['status'], pvc['volume'], pvc['capacity'], pvc['access_modes'], pvc['storage_class'])
        
        console.print(table)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return

def describe_resource(console, core_v1_api, apps_v1_api):
    """Handles the interactive selection and display of a described resource."""
    try:
        console.print("\n---[ Select a Resource Type to Describe ]---")
        resource_type = Prompt.ask("Choose resource type", choices=["Pod", "Deployment", "Node", "Service"], default="Pod")

        description, error = None, None

        if resource_type == "Node":
            name = Prompt.ask("Enter Node name")
            if name:
                description, error = k8s_actions.describe_resource(core_v1_api, apps_v1_api, resource_type, name)
        else: # Pod, Deployment, or Service
            namespace = Prompt.ask("Enter namespace", default="default")
            name = Prompt.ask(f"Enter {resource_type} name")
            if namespace and name:
                description, error = k8s_actions.describe_resource(core_v1_api, apps_v1_api, resource_type, name, namespace)

        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
        elif description:
            console.print(Panel(description, title=f"Description for {resource_type}: {name}", border_style="green"))
        else:
            console.print("[yellow]No name entered or operation cancelled.[/yellow]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return

def display_host_utilization(console, history):
    """Displays host resource utilization in a table and a historical graph."""
    console.print("\n[bold]Fetching host resource usage...[/bold]")
    try:
        util = host_actions.get_resource_utilization()
        
        # --- Update History ---
        history['cpu'].append(util['cpu_percent'])
        history['mem'].append(util['memory'].percent)

        # --- Display Table ---
        table = Table(title="Host Resource Utilization", show_header=True)
        table.add_column("Resource", style="cyan")
        table.add_column("Usage", style="magenta", justify="right")
        table.add_column("Details", style="green")

        mem = util['memory']
        disk = util['disk_root']
        
        table.add_row("CPU", f"{util['cpu_percent']:.1f}%", "")
        table.add_row("Memory", f"{mem.percent:.1f}%", f"{mem.used/1024**3:.2f}GiB / {mem.total/1024**3:.2f}GiB")
        table.add_row("Disk (/)", f"{disk.percent:.1f}%", f"{disk.used/1024**3:.2f}GiB / {disk.total/1024**3:.2f}GiB")

        console.print(table)

        # --- Display Graph ---
        plt.clf()
        plt.subplots(1, 2)
        
        plt.subplot(1, 1)
        plt.title("CPU Usage History (%)")
        plt.plot(list(history['cpu']), color="blue")
        
        plt.subplot(1, 2)
        plt.title("Memory Usage History (%)")
        plt.plot(list(history['mem']), color="magenta")
        
        plt.show()
        console.print("[dim]Graphs show the last 60 data points.[/dim]")

    except Exception as e:
        console.print(f"[bold red]Error fetching host utilization: {e}[/bold red]")

def display_process_explorer(console):
    """Displays a list of running processes, sorted by CPU or memory."""
    try:
        console.print("\n[bold]Fetching process list...[/bold]")
        sort_choice = Prompt.ask("Sort by", choices=["cpu", "memory"], default="cpu")
        limit = IntPrompt.ask("Limit to top N processes", default=20)

        processes = host_actions.get_process_list(sort_by=f"{sort_choice}_percent", limit=limit)

        if not processes:
            console.print("[yellow]No processes found or access denied.[/yellow]")
            return

        table = Table(title=f"Top {limit} Processes (Sorted by {sort_choice.upper()})")
        table.add_column("PID", style="cyan", justify="right")
        table.add_column("Name", style="magenta")
        table.add_column("Status", style="blue")
        table.add_column("CPU %", style="green", justify="right")
        table.add_column("MEM %", style="yellow", justify="right")
        table.add_column("Command", style="red")

        for p in processes:
            table.add_row(
                str(p['pid']),
                p['name'],
                p['status'],
                f"{p['cpu_percent']:.1f}",
                f"{p['memory_percent']:.1f}",
                p['cmdline']
            )
        console.print(table)

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return
    except Exception as e:
        console.print(f"[bold red]Error fetching process list: {e}[/bold red]")


def display_docker_containers(console):
    """Displays a list of Docker containers running on the host."""
    try:
        console.print("\n[bold]Fetching Docker containers...[/bold]")
        containers, error = host_actions.get_docker_containers()

        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
            console.print("[yellow]Ensure Docker is running and your user has permissions (e.g., in 'docker' group or running with sudo).[/yellow]")
            return
        if not containers:
            console.print("[yellow]No Docker containers found.[/yellow]")
            return

        table = Table(title="Docker Containers")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="magenta")
        table.add_column("Image", style="blue")
        table.add_column("Status", style="green")
        table.add_column("Ports", style="yellow")

        for c in containers:
            table.add_row(c['id'], c['name'], c['image'], c['status'], c['ports'])
        
        console.print(table)

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return
    except Exception as e:
        console.print(f"[bold red]Error fetching Docker containers: {e}[/bold red]")


def display_host_logs(console):
    """Displays a sub-menu to select and view configured host logs with a summary."""
    try:
        console.print("\n[bold]Loading log configurations...[/bold]")
        log_configs, error = host_actions.load_log_config()
        if error:
            console.print(f"[bold red]{error}[/bold red]")
            return
        if not log_configs:
            console.print("[yellow]No logs configured in config.yml[/yellow]")
            return

        log_choices = {str(i+1): entry for i, entry in enumerate(log_configs)}

        console.print("---[ Select a Log to View ]---")
        for i, entry in log_choices.items():
            console.print(f"{i}. {entry['display_name']}")
        
        choice = Prompt.ask("[bold]Choose a log[/bold]", choices=list(log_choices.keys()))
        selected_entry = log_choices[choice]

        console.print(f"\n[bold]Fetching and parsing log for '{selected_entry['display_name']}'...[/bold]")
        styled_content, summary, error = host_actions.get_log_output(selected_entry)

        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
            return

        # Display Summary Table
        summary_table = Table(title="Log Analysis Summary")
        summary_table.add_column("Rule", style="cyan")
        summary_table.add_column("Count", style="magenta", justify="right")
        summary_table.add_column("Threshold", style="blue", justify="right")
        summary_table.add_column("Status", justify="center")

        for name, data in summary.items():
            count = data['count']
            threshold = data['threshold']
            status = f"[bold red]BREACHED[/]" if count >= threshold else "[green]OK[/]"
            summary_table.add_row(name, str(count), str(threshold), status)
        
        console.print(summary_table)

        # Display Log Content
        panel_title = f"Log: {selected_entry['display_name']}"
        console.print(Panel(styled_content, title=panel_title, border_style="green"))

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return


def display_network_stats(console):
    """Displays host network statistics."""
    console.print("\n[bold]Fetching host network stats...[/bold]")
    try:
        stats, error = host_actions.get_network_stats()
        
        if error:
            console.print(f"[bold red]Error: {error}[/bold red]")
            return
        if not stats:
            console.print("[yellow]No network interfaces found.[/yellow]")
            return

        table = Table(title="Host Network Statistics")
        table.add_column("Interface", style="cyan")
        table.add_column("IP Address", style="blue")
        table.add_column("Bytes Sent", style="magenta", justify="right")
        table.add_column("Bytes Recv", style="green", justify="right")
        table.add_column("Errors (In/Out)", style="red", justify="right")
        table.add_column("Dropped (In/Out)", style="yellow", justify="right")

        for s in stats:
            errors = f"{s['errin']}/{s['errout']}"
            dropped = f"{s['dropin']}/{s['dropout']}"
            table.add_row(s['interface'], s['ip_address'], s['bytes_sent'], s['bytes_recv'], errors, dropped)
        
        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Error fetching network stats: {e}[/bold red]")

def display_node_info(console, core_v1_api):
    """Handles the logic for displaying node information."""
    console.print("\n[bold]Fetching node information...[/bold]")
    nodes = k8s_actions.get_node_info(core_v1_api)
    if not nodes:
        console.print("[yellow]Could not retrieve node information.[/yellow]")
        return

    table = Table(title="Cluster Node Information")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Roles", style="blue")
    table.add_column("Internal IP", style="green")
    table.add_column("Kubelet Version", style="yellow")

    for node in nodes:
        table.add_row(node['name'], node['status'], node['roles'], node['ip'], node['version'])
    
    console.print(table)

def display_namespaces(console, core_v1_api):
    """Handles the logic for displaying namespaces."""
    console.print("\n[bold]Fetching namespaces...[/bold]")
    namespaces = k8s_actions.list_namespaces(core_v1_api)
    if not namespaces:
        console.print("[yellow]Could not retrieve namespaces.[/yellow]")
        return

    table = Table(title="Cluster Namespaces")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="magenta")

    for ns in namespaces:
        table.add_row(ns['name'], ns['status'])
    
    console.print(table)

def display_resource_quotas(console, core_v1_api):
    """Handles the logic for displaying resource quotas."""
    try:
        namespace = Prompt.ask("Enter namespace", default="default")
        console.print(f"\n[bold]Fetching resource quotas for namespace: {namespace}...[/bold]")
        quotas = k8s_actions.get_resource_quotas(core_v1_api, namespace)
        if not quotas:
            console.print(f"[yellow]No resource quotas found in namespace '{namespace}'.[/yellow]")
            return

        for quota in quotas:
            table = Table(title=f"Resource Quota: '{quota['name']}' in Namespace: {namespace}")
            table.add_column("Resource", style="cyan")
            table.add_column("Hard Limit", style="magenta")
            table.add_column("Used", style="green")
            
            for resource, limit in quota['hard'].items():
                used = quota['used'].get(resource, "N/A")
                table.add_row(resource, limit, used)
            console.print(table)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return

def display_pod_status(console, core_v1_api, custom_objects_api):
    """Handles the logic for displaying pod status and metrics with live filtering."""
    try:
        namespace_input = Prompt.ask("Enter namespace ('all' for all, press Enter for 'default')")
        namespace = namespace_input.strip() or "default"
        
        console.print(f"\n[bold]Fetching pod status and metrics for namespace: {namespace}...[/bold]")
        console.print("[dim]Type to filter by name, press Enter to refresh, Ctrl+C to exit.[/dim]")

        filter_text = ""

        def generate_table(pods, filter_str):
            table = Table(title=f"Pod Status & Usage in Namespace: {namespace} (Filter: '{filter_str}')")
            table.add_column("Name", style="cyan")
            table.add_column("Status", style="magenta")
            table.add_column("IP Address", style="green")
            table.add_column("Namespace", style="blue")
            table.add_column("CPU", style="yellow")
            table.add_column("Memory", style="red")

            for pod in pods:
                if filter_str.lower() in pod['name'].lower():
                    table.add_row(pod['name'], pod['status'], pod['ip'], pod['namespace'], pod['cpu'], pod['memory'])
            return table

        with Live(console=console, screen=True, auto_refresh=False) as live:
            while True:
                pods, error = k8s_actions.get_pod_status(core_v1_api, custom_objects_api, namespace)
                
                if error:
                    live.console.print(f"[yellow]Note: {error}[/yellow]")
                if not pods:
                    live.console.print(f"[yellow]No pods found in namespace '{namespace}' or access denied.[/yellow]")
                    break

                live.update(generate_table(pods, filter_text), refresh=True)

                # Non-blocking key press check would be ideal, but rich doesn't support it directly.
                # We'll use a prompt that the user can interact with.
                filter_text = Prompt.ask(f"[bold]Filter by name (current: '{filter_text}')[/bold]", default=filter_text)

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")

def display_deployment_status(console, core_v1_api, apps_v1_api, custom_objects_api):
    """Handles the logic for displaying deployment status and metrics with live filtering."""
    try:
        namespace_input = Prompt.ask("Enter namespace ('all' for all, press Enter for 'default')")
        namespace = namespace_input.strip() or "default"

        console.print(f"\n[bold]Fetching deployment status and metrics for namespace: {namespace}...[/bold]")
        console.print("[dim]Type to filter by name, press Enter to refresh, Ctrl+C to exit.[/dim]")
        
        filter_text = ""

        def generate_table(deployments, filter_str):
            table = Table(title=f"Deployment Status & Usage in Namespace: {namespace} (Filter: '{filter_str}')")
            table.add_column("Name", style="cyan")
            table.add_column("Namespace", style="blue")
            table.add_column("Replicas (Ready/Desired)", style="green")
            table.add_column("Pod Count", style="yellow")
            table.add_column("Total CPU (cores)", style="magenta")
            table.add_column("Total Memory (MiB)", style="red")

            for dep in deployments:
                if filter_str.lower() in dep['name'].lower():
                    table.add_row(
                        dep['name'],
                        dep['namespace'],
                        f"{dep['ready_replicas']}/{dep['replicas']}",
                        str(dep['pod_count']),
                        f"{dep['cpu'] / 1000:.3f}",
                        f"{dep['memory'] / 1024:.2f}"
                    )
            return table

        with Live(console=console, screen=True, auto_refresh=False) as live:
            while True:
                deployments, error = k8s_actions.get_deployment_status(core_v1_api, apps_v1_api, custom_objects_api, namespace)
                
                if error:
                    live.console.print(f"[yellow]Note: {error}[/yellow]")
                if not deployments:
                    live.console.print(f"[yellow]No deployments found in namespace '{namespace}' or access denied.[/yellow]")
                    break

                live.update(generate_table(deployments, filter_text), refresh=True)
                
                filter_text = Prompt.ask(f"[bold]Filter by name (current: '{filter_text}')[/bold]", default=filter_text)

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")

def display_pod_logs(console, core_v1_api):
    """Handles the logic for displaying pod logs."""
    try:
        namespace = Prompt.ask("Enter namespace", default="default")
        pod_name = Prompt.ask("Enter pod name")

        if not pod_name:
            console.print("[red]Pod name cannot be empty.[/red]")
            return

        console.print(f"\n[bold]Fetching logs for pod '{pod_name}' in namespace '{namespace}'...[/bold]")
        logs = k8s_actions.get_pod_logs(core_v1_api, namespace, pod_name)

        if logs:
            console.print(Panel(logs, title=f"Logs for {pod_name}", border_style="green"))
        else:
            console.print(f"[yellow]No logs returned for pod '{pod_name}'. It may not exist or has no logs.[/yellow]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return

def edit_deployment(console, apps_v1_api):
    """Handles the interactive editing of a deployment."""
    try:
        namespace = Prompt.ask("Enter namespace", default="default")
        deployment_name = Prompt.ask("Enter deployment name")
        if not deployment_name:
            console.print("[red]Deployment name cannot be empty.[/red]")
            return

        # Fetch the deployment
        try:
            deployment = apps_v1_api.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        except Exception as e:
            console.print(f"[bold red]Error fetching deployment: {e}[/bold red]")
            return

        console.print("\n---[ What do you want to edit? ]---")
        edit_choice = Prompt.ask("Choose an option", choices=["Container Image", "Resource Limits/Requests"], default="Container Image")

        if edit_choice == "Container Image":
            edit_deployment_image(console, apps_v1_api, deployment)
        elif edit_choice == "Resource Limits/Requests":
            edit_deployment_resources(console, apps_v1_api, deployment)

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")

def edit_deployment_image(console, apps_v1_api, deployment):
    """Handles editing a deployment's container image."""
    namespace = deployment.metadata.namespace
    deployment_name = deployment.metadata.name

    console.print(f"\n[bold]Current containers in '{deployment_name}':[/bold]")
    for i, container in enumerate(deployment.spec.template.spec.containers):
        console.print(f"  {i+1}. {container.name} (Image: {container.image})")

    container_index = IntPrompt.ask("Choose a container number to edit", choices=[str(i+1) for i, _ in enumerate(deployment.spec.template.spec.containers)], default="1")
    container_name = deployment.spec.template.spec.containers[container_index-1].name
    
    new_image = Prompt.ask(f"Enter the new image for container '{container_name}'")

    if Confirm.ask(f"Update container '{container_name}' in deployment '{deployment_name}' to image '{new_image}'?"):
        success, message = k8s_actions.patch_deployment_image(apps_v1_api, namespace, deployment_name, container_name, new_image)
        if success:
            console.print(f"[green]✔ {message}[/green]")
        else:
            console.print(f"[bold red]✖ Error: {message}[/bold red]")
    else:
        console.print("[yellow]Edit cancelled.[/yellow]")

def edit_deployment_resources(console, apps_v1_api, deployment):
    """Handles editing a deployment's resource limits and requests."""
    namespace = deployment.metadata.namespace
    deployment_name = deployment.metadata.name

    console.print(f"\n[bold]Current containers in '{deployment_name}':[/bold]")
    for i, container in enumerate(deployment.spec.template.spec.containers):
        console.print(f"  {i+1}. {container.name}")

    container_index = IntPrompt.ask("Choose a container number to edit", choices=[str(i+1) for i, _ in enumerate(deployment.spec.template.spec.containers)], default="1")
    container = deployment.spec.template.spec.containers[container_index-1]
    
    console.print(f"\n[bold]Current resources for '{container.name}':[/bold]")
    console.print(f"  Requests: CPU={container.resources.requests.get('cpu', 'N/A')}, Memory={container.resources.requests.get('memory', 'N/A')}")
    console.print(f"  Limits:   CPU={container.resources.limits.get('cpu', 'N/A')}, Memory={container.resources.limits.get('memory', 'N/A')}")

    console.print("\nEnter new resource values (leave blank to keep current). Examples: CPU='500m', Memory='256Mi'")
    new_resources = {
        "requests": {
            "cpu": Prompt.ask("New CPU Request", default=container.resources.requests.get('cpu')),
            "memory": Prompt.ask("New Memory Request", default=container.resources.requests.get('memory'))
        },
        "limits": {
            "cpu": Prompt.ask("New CPU Limit", default=container.resources.limits.get('cpu')),
            "memory": Prompt.ask("New Memory Limit", default=container.resources.limits.get('memory'))
        }
    }

    if Confirm.ask(f"Apply new resources to container '{container.name}' in deployment '{deployment_name}'?"):
        success, message = k8s_actions.patch_deployment_resources(apps_v1_api, namespace, deployment_name, container.name, new_resources)
        if success:
            console.print(f"[green]✔ {message}[/green]")
        else:
            console.print(f"[bold red]✖ Error: {message}[/bold red]")
    else:
        console.print("[yellow]Edit cancelled.[/yellow]")

def scale_deployment_replicas(console, apps_v1_api):
    """Handles the interactive scaling of a deployment."""
    try:
        namespace = Prompt.ask("Enter namespace", default="default")
        deployment_name = Prompt.ask("Enter deployment name")
        if not deployment_name:
            console.print("[red]Deployment name cannot be empty.[/red]")
            return
        
        replicas = IntPrompt.ask("Enter the desired number of replicas")

        if Confirm.ask(f"Scale deployment '{deployment_name}' in namespace '{namespace}' to {replicas} replicas?"):
            success, message = k8s_actions.scale_deployment(apps_v1_api, namespace, deployment_name, replicas)
            if success:
                console.print(f"[green]✔ {message}[/green]")
            else:
                console.print(f"[bold red]✖ Error: {message}[/bold red]")
        else:
            console.print("[yellow]Scaling cancelled.[/yellow]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. Returning to main menu.[/yellow]")
        return

def interactive_mode():
    """Runs the application in interactive menu mode."""
    console = Console()
    core_v1_api, apps_v1_api, custom_objects_api = k8s_actions.init_clients()

    # Data store for historical graphs
    host_history = {
        "cpu": deque(maxlen=60),
        "mem": deque(maxlen=60)
    }

    if not all([core_v1_api, apps_v1_api, custom_objects_api]):
        console.print("[bold red]Failed to initialize Kubernetes clients. Exiting.[/bold red]")
        sys.exit(1)

    while True:
        try:
            choice = show_menu(console)
            if choice == '1':
                display_dashboard(console, core_v1_api, apps_v1_api, custom_objects_api)
            elif choice == '2':
                display_node_info(console, core_v1_api)
            elif choice == '3':
                display_namespaces(console, core_v1_api)
            elif choice == '4':
                display_services(console, core_v1_api)
            elif choice == '5':
                display_event_stream(console, core_v1_api)
            elif choice == '6':
                display_resource_quotas(console, core_v1_api)
            elif choice == '7':
                display_pod_status(console, core_v1_api, custom_objects_api)
            elif choice == '8':
                display_deployment_status(console, core_v1_api, apps_v1_api, custom_objects_api)
            elif choice == '9':
                display_pod_logs(console, core_v1_api)
            elif choice == '10':
                open_pod_shell(console, core_v1_api)
            elif choice == '11':
                scale_deployment_replicas(console, apps_v1_api)
            elif choice == '12':
                edit_deployment(console, apps_v1_api)
            elif choice == '13':
                display_persistent_volumes(console, core_v1_api)
            elif choice == '14':
                display_persistent_volume_claims(console, core_v1_api)
            elif choice == '15':
                display_configmaps(console, core_v1_api)
            elif choice == '16':
                display_secrets(console, core_v1_api)
            elif choice == '17':
                display_resource_yaml(console, core_v1_api, apps_v1_api)
            elif choice == '18':
                describe_resource(console, core_v1_api, apps_v1_api)
            elif choice == '19':
                display_host_utilization(console, host_history)
            elif choice == '20':
                display_process_explorer(console)
            elif choice == '21':
                display_docker_containers(console)
            elif choice == '22':
                display_host_logs(console)
            elif choice == '23':
                display_network_stats(console)
            elif choice == '24':
                console.print("[bold]Exiting. Goodbye![/bold]")
                break
            else:
                console.print("[bold red]Invalid option. Please try again.[/bold red]")
        except KeyboardInterrupt:
            console.print("\n[bold]Exiting. Goodbye![/bold]")
            break
        except Exception as e:
            console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")

def main():
    """Main entry point for the application."""
    # Log the application start time
    alerter.log_program_start()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(description="A unified monitor for Kubernetes and host systems.")
    parser.add_argument('--mode', choices=['interactive', 'watcher'], default='interactive', help='Run in interactive mode or non-interactive watcher mode.')
    args = parser.parse_args()

    if args.mode == 'watcher':
        watcher.start_watcher()
    else:
        interactive_mode()

if __name__ == "__main__":
    main()