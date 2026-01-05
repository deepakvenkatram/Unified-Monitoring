import os
import psutil
import yaml
import subprocess
from pathlib import Path
import docker # type: ignore
from docker.errors import DockerException # type: ignore

CONFIG_PATH = "config.yml"

def check_path_accessibility(path: str):
    """
    Checks if a given file system path exists and is readable.

    Args:
        path (str): The file system path to check.

    Returns:
        tuple: (is_accessible: bool, message: str)
               is_accessible is True if the path exists and is readable, False otherwise.
               message provides details if not accessible, None otherwise.
    """
    if not os.path.exists(path):
        return False, f"Path '{path}' does not exist."
    if not os.access(path, os.R_OK):
        return False, f"Permission denied to read path '{path}'."
    return True, None

def get_resource_utilization():
    """
    Fetches host CPU, memory, and disk utilization using psutil.
    """
    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory": psutil.virtual_memory(),
        "disk_root": psutil.disk_usage('/'),
    }

def get_process_list(sort_by='cpu_percent', limit=20):
    """
    Fetches a list of running processes, sorted by CPU or memory usage.
    """
    processes = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status', 'cmdline']):
        try:
            # Accessing attributes might raise NoSuchProcess or AccessDenied
            processes.append({
                'pid': p.info['pid'],
                'name': p.info['name'],
                'cpu_percent': p.info['cpu_percent'],
                'memory_percent': p.info['memory_percent'],
                'status': p.info['status'],
                'cmdline': ' '.join(p.info['cmdline']) if p.info['cmdline'] else p.info['name'],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Ignore processes that disappear or are inaccessible
            continue
    
    # Sort processes
    if sort_by == 'cpu_percent':
        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
    elif sort_by == 'memory_percent':
        processes.sort(key=lambda x: x['memory_percent'], reverse=True)
    
    return processes[:limit]

def get_docker_containers():
    """
    Fetches a list of Docker containers running on the host.
    """
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True) # Get all containers, running or not
        
        container_data = []
        for container in containers:
            ports = []
            for p_key, p_val in container.ports.items():
                if p_val:
                    for item in p_val:
                        if 'HostPort' in item:
                            ports.append(f"{p_key}->{item['HostPort']}/{item['HostIp'] or '0.0.0.0'}")
                        else:
                            ports.append(f"{p_key}")
                else:
                    ports.append(f"{p_key}")

            container_data.append({
                'id': container.short_id,
                'name': container.name,
                'image': container.image.tags[0] if container.image.tags else 'N/A',
                'status': container.status,
                'ports': ", ".join(ports) if ports else 'N/A',
            })
        return container_data, None
    except DockerException as e:
        return [], f"Error connecting to Docker daemon: {e}. Ensure Docker is running and you have permissions (e.g., user in 'docker' group or sudo)."
    except Exception as e:
        return [], f"An unexpected error occurred: {e}"

def get_network_connections():
    """
    Fetches active network connections and associated process information.
    """
    connections = []
    for conn in psutil.net_connections(kind='inet'):
        try:
            p = psutil.Process(conn.pid) if conn.pid else None
            connections.append({
                'fd': conn.fd,
                'family': conn.family.name,
                'type': conn.type.name,
                'laddr': f"{conn.laddr.ip}:{conn.laddr.port}",
                'raddr': f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A",
                'status': conn.status,
                'pid': conn.pid,
                'process_name': p.name() if p else "N/A",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            connections.append({
                'fd': conn.fd,
                'family': conn.family.name,
                'type': conn.type.name,
                'laddr': f"{conn.laddr.ip}:{conn.laddr.port}",
                'raddr': f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A",
                'status': conn.status,
                'pid': conn.pid,
                'process_name': "Access Denied/N/A",
            })
        except Exception:
            # Catch other potential errors during process lookup
            pass
    return connections, None

def get_listening_ports():
    """
    Fetches listening ports and associated process information.
    """
    listening_ports = []
    for conn in psutil.net_connections(kind='inet'):
        if conn.status == psutil.CONN_LISTEN:
            try:
                p = psutil.Process(conn.pid) if conn.pid else None
                listening_ports.append({
                    'laddr': f"{conn.laddr.ip}:{conn.laddr.port}",
                    'pid': conn.pid,
                    'process_name': p.name() if p else "N/A",
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                listening_ports.append({
                    'laddr': f"{conn.laddr.ip}:{conn.laddr.port}",
                    'pid': conn.pid,
                    'process_name': "Access Denied/N/A",
                })
            except Exception:
                pass
    return listening_ports, None


def get_network_stats():
    """
    Fetches network interface statistics using psutil.
    """
    stats = psutil.net_io_counters(pernic=True)
    addrs = psutil.net_if_addrs()
    
    results = []
    for iface, iface_stats in stats.items():
        # Safely get addresses
        iface_addrs = addrs.get(iface, [])
        ip_address = "N/A"
        for addr in iface_addrs:
            if addr.family == psutil.AF_LINK: # This is the MAC address
                continue
            if addr.family == 2: # AF_INET (IPv4)
                ip_address = addr.address
                break # Prefer IPv4 for display
        
        results.append({
            "interface": iface,
            "ip_address": ip_address,
            "bytes_sent": f"{iface_stats.bytes_sent / 1024**2:.2f} MB",
            "bytes_recv": f"{iface_stats.bytes_recv / 1024**2:.2f} MB",
            "packets_sent": iface_stats.packets_sent,
            "packets_recv": iface_stats.packets_recv,
            "errin": iface_stats.errin,
            "errout": iface_stats.errout,
            "dropin": iface_stats.dropin,
            "dropout": iface_stats.dropout,
        })
    return results, None

def _load_config_section(section_name, default_value):
    """Generic helper to load a section from the config file."""
    config_file = Path(CONFIG_PATH)
    if not config_file.is_file():
        return None, f"Configuration file not found at '{CONFIG_PATH}'"
    
    with open(config_file, 'r') as f:
        try:
            config = yaml.safe_load(f)
            return config.get(section_name, default_value), None
        except yaml.YAMLError as e:
            return None, f"Error parsing YAML file: {e}"

def load_log_config():
    """Loads the list of log source configurations from config.yml."""
    return _load_config_section('logs', [])

def load_parsing_rules():
    """Loads the log parsing rules from config.yml."""
    return _load_config_section('log_parsing_rules', [])


def get_log_output(log_entry: dict, tail_lines: int = 200):
    """
    Gets log output, parses it for keywords, and returns a styled string and summary.
    """
    # 1. Get raw log content
    raw_content, error, is_error = "", "", False
    if 'path' in log_entry:
        log_path_str = log_entry['path']
        log_path = Path(log_path_str)
        if not log_path.is_file():
            return None, None, f"Error: Log file not found at '{log_path_str}'"
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                raw_content = "".join(lines[-tail_lines:])
        except PermissionError:
            return None, None, f"Error: Permission denied to read '{log_path_str}'. Try running with sudo."
        except Exception as e:
            return None, None, f"An unexpected error occurred while reading the file: {e}"

    elif 'command' in log_entry:
        command = log_entry['command']
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
            raw_content = result.stdout
        except subprocess.CalledProcessError as e:
            return None, None, f"Command failed with exit code {e.returncode}:\n{e.stderr}"
        except Exception as e:
            return None, None, f"An unexpected error occurred while running the command: {e}"
    else:
        return None, None, "Error: Log entry must contain either a 'path' or a 'command'."

    # 2. Parse and style the content
    rules, error = load_parsing_rules()
    if error:
        return None, None, f"Could not load parsing rules: {error}"

    summary = {rule['name']: {'count': 0, 'threshold': rule['threshold'], 'color': rule['color']} for rule in rules}
    styled_lines = []
    
    for line in raw_content.splitlines():
        styled = False
        for rule in rules:
            for keyword in rule['keywords']:
                if keyword.lower() in line.lower():
                    rule_name = rule['name']
                    summary[rule_name]['count'] += 1
                    color = rule['color']
                    # Use escape=False for Panel to render highlights correctly
                    styled_lines.append(f"[{color}]{line}[/{color}]")
                    styled = True
                    break  # Stop after first keyword match in a rule
            if styled:
                break # Stop after first rule match for a line
        if not styled:
            styled_lines.append(line)

    return "\n".join(styled_lines), summary, None
