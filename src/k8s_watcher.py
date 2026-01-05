import time
import yaml
import re
from datetime import datetime, timedelta
from pathlib import Path
from . import k8s_actions, alerter, host_actions

# --- ANSI Color Codes ---
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_GREEN = "\033[92m"
COLOR_RESET = "\033[0m"

# --- State Management ---
ACTIVE_POD_ISSUES = set()
ACTIVE_LOG_ALERTS = set() # For configured pod log monitoring
ACTIVE_NETWORK_PATH_ISSUES = set()
ACTIVE_RESOURCE_ISSUES = set()
ACTIVE_DEPLOYMENT_ISSUES = set()
ACTIVE_METRICS_ERROR = set()
ACTIVE_GLOBAL_POD_LOG_ALERTS = set() # New state for global pod log alerts
ISSUE_ACTIVE_CYCLES = {} # Used for ongoing alerts
NOTIFIED_COMPLETED_PODS = set()
ALERT_BUFFER = []
LOG_MONITOR_STATE = {} # For configured pod log monitoring
DEPLOYMENT_ROLLOUT_STATE = {}

# --- Configuration Loading ---

def _load_watcher_config():
    config_file = Path("config.yml")
    if not config_file.is_file():
        return None, "Configuration file config.yml not found."
    with open(config_file, 'r') as f:
        try:
            return yaml.safe_load(f), None
        except yaml.YAMLError as e:
            return None, f"Error parsing YAML file: {e}"

# --- Time Window Parsing ---

def _parse_time_window(time_str):
    if not time_str or not isinstance(time_str, str): return timedelta(minutes=10)
    unit = time_str[-1].lower()
    try:
        value = int(time_str[:-1])
        if unit == 'm': return timedelta(minutes=value)
        if unit == 'h': return timedelta(hours=value)
        if unit == 'd': return timedelta(days=value)
    except (ValueError, TypeError): pass
    return timedelta(minutes=10)

# --- Core Watcher Functions ---

def check_metrics_server_status(custom_objects_api, config):
    """
    Checks if the metrics server is available by attempting to fetch pod metrics.
    Triggers an alert if unavailable, and a resolved alert if it recovers.
    """
    global ACTIVE_METRICS_ERROR, ALERT_BUFFER
    issue_key = "metrics_server_unavailable"
    
    # Attempt to fetch metrics for a single pod to check server status
    # Use kube-system for a common pod, but check if it exists first
    try:
        # Try to list pods in kube-system to ensure namespace exists
        core_v1_api = k8s_actions.init_clients()[0] # Temporarily get core_v1_api
        if not core_v1_api: raise Exception("CoreV1Api not initialized")
        core_v1_api.list_namespaced_pod("kube-system", limit=1)
    except Exception:
        # If kube-system doesn't exist or API fails, use default
        namespace_to_check = "default"
    else:
        namespace_to_check = "kube-system"

    _, error = k8s_actions.get_pod_metrics(custom_objects_api, namespace=namespace_to_check)
    
    if error:
        if issue_key not in ACTIVE_METRICS_ERROR:
            subject = "Kubernetes Metrics Server Unavailable"
            body = f"The Kubernetes Metrics Server is currently unavailable or returning errors.\nError: {error}"
            ALERT_BUFFER.append({"grouping_key": "Metrics Server Status", "subject": subject, "body": body, "severity": "ALERT"})
            ACTIVE_METRICS_ERROR.add(issue_key)
    else:
        if issue_key in ACTIVE_METRICS_ERROR:
            subject = "RESOLVED: Kubernetes Metrics Server Available"
            body = "The Kubernetes Metrics Server is now available and responding to requests."
            ALERT_BUFFER.append({"grouping_key": "Metrics Server Status", "subject": subject, "body": body, "severity": "RESOLVED"})
            ACTIVE_METRICS_ERROR.remove(issue_key)


def check_deployment_health(core_v1_api, apps_v1_api, custom_objects_api, config):
    """
    Checks for deployment health issues like stuck rollouts or unavailable replicas.
    """
    global ACTIVE_DEPLOYMENT_ISSUES, ALERT_BUFFER, DEPLOYMENT_ROLLOUT_STATE
    deploy_config = config.get('deployment_health_monitoring', {})
    if not deploy_config.get('enabled'): return

    print("K8s Watcher: Checking deployment health...")
    
    unavailable_threshold = deploy_config.get('unavailable_replicas_threshold', 0)
    stuck_rollout_timeout = deploy_config.get('stuck_rollout_timeout_seconds', 300)
    
    deployments, error = k8s_actions.get_deployment_status(core_v1_api, apps_v1_api, custom_objects_api, "all")
    if error:
        print(f"K8s Watcher Error: Could not get deployment status: {error}")
        return

    current_deploy_issues = set()
    now = datetime.now()

    for dep in deployments:
        namespace = dep['namespace']
        name = dep['name']
        desired_replicas = dep['replicas'] or 0
        ready_replicas = dep['ready_replicas'] or 0
        unavailable_replicas = desired_replicas - ready_replicas

        # --- Check for Unavailable Replicas ---
        if unavailable_replicas > unavailable_threshold:
            issue_key = f"deployment_unavailable/{namespace}/{name}"
            current_deploy_issues.add(issue_key)
            if issue_key not in ACTIVE_DEPLOYMENT_ISSUES:
                subject = f"Deployment '{name}' has Unavailable Replicas"
                body = (f"Deployment '{name}' in namespace '{namespace}' has {unavailable_replicas} unavailable replicas.\n"
                        f"Desired: {desired_replicas}, Ready: {ready_replicas}")
                ALERT_BUFFER.append({"grouping_key": f"Deployment Unavailable:{namespace}", "subject": subject, "body": body, "severity": "ALERT"})
                ACTIVE_DEPLOYMENT_ISSUES.add(issue_key)
        
        # --- Check for Stuck Rollouts ---
        is_progressing = False
        is_stuck_failed = False
        for condition in dep.get('conditions', []):
            if condition.type == 'Progressing':
                if condition.status == 'True':
                    is_progressing = True
                elif condition.status == 'False' and condition.reason == 'FailedDeployment':
                    is_stuck_failed = True
            
        if (ready_replicas < desired_replicas and is_progressing) or is_stuck_failed:
            rollout_key = f"deployment_stuck/{namespace}/{name}"
            
            if rollout_key not in DEPLOYMENT_ROLLOUT_STATE:
                DEPLOYMENT_ROLLOUT_STATE[rollout_key] = now
            
            if (now - DEPLOYMENT_ROLLOUT_STATE[rollout_key]).total_seconds() >= stuck_rollout_timeout:
                current_deploy_issues.add(rollout_key)
                if rollout_key not in ACTIVE_DEPLOYMENT_ISSUES:
                    subject = f"Deployment '{name}' Rollout Stuck"
                    body = (f"Deployment '{name}' in namespace '{namespace}' has been stuck in rollout for over {stuck_rollout_timeout} seconds.\n"
                            f"Desired: {desired_replicas}, Ready: {ready_replicas}")
                    ALERT_BUFFER.append({"grouping_key": f"Deployment Stuck:{namespace}", "subject": subject, "body": body, "severity": "ALERT"})
                    ACTIVE_DEPLOYMENT_ISSUES.add(rollout_key)
        else:
            if f"deployment_stuck/{namespace}/{name}" in DEPLOYMENT_ROLLOUT_STATE:
                del DEPLOYMENT_ROLLOUT_STATE[f"deployment_stuck/{namespace}/{name}"]

    # Handle resolved deployment issues
    resolved_deploy_issues = ACTIVE_DEPLOYMENT_ISSUES - current_deploy_issues
    for issue_key in resolved_deploy_issues:
        _, namespace, name = issue_key.split('/')[:3]
        issue_type = "Unavailable Replicas" if "unavailable" in issue_key else "Rollout Stuck"
        subject = f"RESOLVED: Deployment '{name}' Health Issue"
        body = f"Deployment '{name}' in '{namespace}' has resolved its '{issue_type}' issue."
        ALERT_BUFFER.append({"grouping_key": "Resolved", "subject": subject, "body": body, "severity": "RESOLVED"})
        ACTIVE_DEPLOYMENT_ISSUES.remove(issue_key)


def check_resource_usage(core_v1_api, custom_objects_api, config):
    """
    Checks if pods are exceeding a percentage of their defined resource limits.
    """
    global ACTIVE_RESOURCE_ISSUES, ALERT_BUFFER
    usage_config = config.get('resource_usage_monitoring', {})
    if not usage_config.get('enabled'): return

    print("K8s Watcher: Checking pod resource usage...")
    
    cpu_threshold = usage_config.get('cpu_threshold_percent', 90)
    mem_threshold = usage_config.get('memory_threshold_percent', 90)

    pod_limits = k8s_actions.get_all_pods_with_limits(core_v1_api)
    pod_metrics, error = k8s_actions.get_pod_metrics(custom_objects_api)

    if error:
        print(f"K8s Watcher Warning: Could not check resource usage: {error}")
        return

    current_breaches = set()

    for (namespace, pod_name), metrics in pod_metrics.items():
        limits = pod_limits.get((namespace, pod_name))
        if not limits: continue

        # Check CPU usage
        if limits["cpu"] > 0:
            cpu_usage_percent = (metrics["cpu_usage_millicores"] / limits["cpu"]) * 100
            if cpu_usage_percent >= cpu_threshold:
                breach_key = f"resource_usage/{namespace}/{pod_name}/cpu"
                current_breaches.add(breach_key)
                if breach_key not in ACTIVE_RESOURCE_ISSUES:
                    subject = f"High CPU Usage on Pod '{pod_name}'"
                    body = (f"CPU usage exceeded {cpu_threshold}% threshold.\n"
                            f"Pod: {pod_name}\nNS: {namespace}\n"
                            f"Usage: {metrics['cpu_usage_millicores']}m ({cpu_usage_percent:.1f}%) | Limit: {limits['cpu']}m")
                    ALERT_BUFFER.append({"grouping_key": f"High CPU Usage:{namespace}", "subject": subject, "body": body, "severity": "ALERT"})
                    ACTIVE_RESOURCE_ISSUES.add(breach_key)

        # Check Memory usage
        if limits["memory"] > 0:
            mem_usage_percent = (metrics["memory_usage_bytes"] / limits["memory"]) * 100
            if mem_usage_percent >= mem_threshold:
                breach_key = f"resource_usage/{namespace}/{pod_name}/memory"
                current_breaches.add(breach_key)
                if breach_key not in ACTIVE_RESOURCE_ISSUES:
                    subject = f"High Memory Usage on Pod '{pod_name}'"
                    body = (f"Memory usage exceeded {mem_threshold}% threshold.\n"
                            f"Pod: {pod_name}\nNS: {namespace}\n"
                            f"Usage: {metrics['memory_usage_bytes'] // 1024**2}Mi ({mem_usage_percent:.1f}%) | Limit: {limits['memory'] // 1024**2}Mi")
                    ALERT_BUFFER.append({"grouping_key": f"High Memory Usage:{namespace}", "subject": subject, "body": body, "severity": "ALERT"})
                    ACTIVE_RESOURCE_ISSUES.add(breach_key)

    # Handle resolved breaches
    resolved_breaches = ACTIVE_RESOURCE_ISSUES - current_breaches
    for breach_key in resolved_breaches:
        _, namespace, name, r_type = breach_key.split('/')
        subject = f"RESOLVED: High {r_type.upper()} Usage on Pod '{name}'"
        body = (
            f"The high {r_type.upper()} usage issue for pod '{name}' in namespace '{namespace}' has been resolved.\n"
            f"Usage is now within the {usage_config.get(f'{r_type}_threshold_percent', 90)}% threshold."
        )
        ALERT_BUFFER.append({"grouping_key": "Resolved", "subject": subject, "body": body, "severity": "RESOLVED"})
        ACTIVE_RESOURCE_ISSUES.remove(breach_key)


def check_pod_statuses(core_v1_api, custom_objects_api, config):
    global ACTIVE_POD_ISSUES, ISSUE_ACTIVE_CYCLES, ALERT_BUFFER
    alert_statuses = config.get('pod_alert_statuses', [])
    ongoing_alert_cycles = config.get('ongoing_alert_cycles', 20)
    if not alert_statuses: return

    print("K8s Watcher: Checking pod statuses...")
    pods, error = k8s_actions.get_pod_status(core_v1_api, custom_objects_api, "all")
    if error:
        print(f"K8s Watcher Error: Could not get pod status: {error}")
        return

    current_issues = set()
    for pod in pods:
        pod_has_issue, determined_status = False, pod['status']
        if pod.get('container_statuses'):
            for status in pod.get('container_statuses'):
                if status.state.waiting and status.state.waiting.reason in alert_statuses:
                    determined_status, pod_has_issue = status.state.waiting.reason, True
                    break
                if status.state.terminated and status.state.terminated.reason in alert_statuses:
                    determined_status, pod_has_issue = status.state.terminated.reason, True
                    break
        if not pod_has_issue and determined_status in alert_statuses:
            pod_has_issue = True

        if pod_has_issue:
            current_issues.add(f"pod_status/{pod['namespace']}/{pod['name']}/{determined_status}")

    new_issues = current_issues - ACTIVE_POD_ISSUES
    resolved_issues = ACTIVE_POD_ISSUES - current_issues
    
    for issue_key in current_issues:
        ISSUE_ACTIVE_CYCLES[issue_key] = ISSUE_ACTIVE_CYCLES.get(issue_key, 0) + 1

    for issue_key in current_issues:
        if issue_key in ACTIVE_POD_ISSUES and ISSUE_ACTIVE_CYCLES[issue_key] > 0 and (ISSUE_ACTIVE_CYCLES[issue_key] % ongoing_alert_cycles == 0):
            _, namespace, name, status = issue_key.split('/')
            subject = f"ONGOING: Pod '{name}' is still in '{status}'"
            body = f"The pod '{name}' in '{namespace}' has been in status '{status}' for {ISSUE_ACTIVE_CYCLES[issue_key]} cycles."
            ALERT_BUFFER.append({"grouping_key": "Ongoing", "subject": subject, "body": body, "severity": "ONGOING"})

    for issue_key in new_issues:
        _, namespace, name, status = issue_key.split('/')
        subject = f"Pod '{name}' is in '{status}' state"
        body = f"A new pod failure has been detected.\nPod: {name}\nNamespace: {namespace}\nStatus: {status}"
        ALERT_BUFFER.append({"grouping_key": f"Pod Failure:{namespace}", "subject": subject, "body": body, "severity": "ALERT"})
        ACTIVE_POD_ISSUES.add(issue_key)

    for issue_key in resolved_issues:
        _, namespace, name, old_status = issue_key.split('/')
        current_status = next((p['status'] for p in pods if p['name'] == name and p['namespace'] == namespace), "Unknown")
        subject = f"RESOLVED: Pod '{name}' is no longer in '{old_status}'"
        body = f"Pod '{name}' in '{namespace}' has recovered.\nPrevious Status: {old_status}\nCurrent Status: {current_status}"
        ALERT_BUFFER.append({"grouping_key": "Resolved", "subject": subject, "body": body, "severity": "RESOLVED"})
        ACTIVE_POD_ISSUES.remove(issue_key)
        ISSUE_ACTIVE_CYCLES.pop(issue_key, None)

def check_pod_logs(core_v1_api, config, interval_seconds):
    global ACTIVE_LOG_ALERTS, LOG_MONITOR_STATE, ISSUE_ACTIVE_CYCLES, ALERT_BUFFER
    log_config = config.get('pod_log_monitoring', {})
    if not log_config.get('enabled'): return

    print("K8s Watcher: Checking pod logs...")
    for target in log_config.get('targets', []):
        target_name = target.get('name', 'Unnamed Target')
        time_window = _parse_time_window(target.get('time_window', '10m'))
        if target_name not in LOG_MONITOR_STATE: LOG_MONITOR_STATE[target_name] = []

        try:
            pod_list = core_v1_api.list_namespaced_pod(target.get('namespace', 'default'), label_selector=target.get('label_selector', '')).items
            for pod in pod_list:
                if pod.status.phase != 'Running': continue
                for container in pod.spec.containers:
                    logs = k8s_actions.get_pod_logs(core_v1_api, pod.metadata.namespace, pod.metadata.name, container=container.name, since_seconds=interval_seconds)
                    if logs:
                        for line in logs.split('\n'):
                            if line and any(re.search(p, line, re.IGNORECASE) for p in target.get('error_patterns', [])):
                                LOG_MONITOR_STATE[target_name].append(datetime.now())
                                break
        except Exception as e:
            print(f"K8s Watcher Warning: Could not process logs for target '{target_name}': {e}")
            continue
        
        now = datetime.now()
        LOG_MONITOR_STATE[target_name] = [ts for ts in LOG_MONITOR_STATE[target_name] if now - ts < time_window]
        
        error_count = len(LOG_MONITOR_STATE[target_name])
        threshold = target.get('threshold', 1)
        is_breached = error_count >= threshold
        is_alerting = target_name in ACTIVE_LOG_ALERTS

        if is_breached and not is_alerting:
            subject = f"Log threshold breached for '{target_name}'"
            body = f"Error threshold breached for '{target_name}'.\nCount: {error_count} errors in the last {target.get('time_window', '10m')}."
            ALERT_BUFFER.append({"grouping_key": f"Log Alert:{target_name}", "subject": subject, "body": body, "severity": "ALERT"})
            ACTIVE_LOG_ALERTS.add(target_name)
        elif not is_breached and is_alerting:
            subject = f"RESOLVED: Log threshold for '{target_name}' is back to normal"
            body = f"The error rate for '{target_name}' has fallen below the threshold.\nCurrent Count: {error_count}."
            ALERT_BUFFER.append({"grouping_key": "Resolved", "subject": subject, "body": body, "severity": "RESOLVED"})
            ACTIVE_LOG_ALERTS.remove(target_name)

def check_all_pod_logs(core_v1_api, config):
    """
    Scans the latest logs of all pods for predefined error and warning patterns.
    """
    global ACTIVE_GLOBAL_POD_LOG_ALERTS, ALERT_BUFFER, ISSUE_ACTIVE_CYCLES
    global_log_config = config.get('global_pod_log_scanning', {})
    if not global_log_config.get('enabled'): return

    print("K8s Watcher: Checking all pod logs for errors/warnings...")
    
    lines_to_scan = global_log_config.get('lines_to_scan', 100)
    error_patterns = [re.compile(p, re.IGNORECASE) for p in global_log_config.get('error_patterns', [])]
    warning_patterns = [re.compile(p, re.IGNORECASE) for p in global_log_config.get('warning_patterns', [])]
    include_namespaces = global_log_config.get('include_namespaces', [])
    exclude_namespaces = global_log_config.get('exclude_namespaces', [])
    ongoing_alert_cycles = config.get('ongoing_alert_cycles', 20)

    all_pods = core_v1_api.list_pod_for_all_namespaces().items
    current_log_issues = set()

    for pod in all_pods:
        namespace = pod.metadata.namespace
        pod_name = pod.metadata.name
        
        # Apply include/exclude logic
        if include_namespaces and namespace not in include_namespaces:
            continue
        if exclude_namespaces and namespace in exclude_namespaces:
            continue

        if pod.status.phase != 'Running': continue # Only check running pods

        for container in pod.spec.containers:
            container_name = container.name
            logs = k8s_actions.get_pod_logs(core_v1_api, namespace, pod_name, container=container_name, tail_lines=lines_to_scan)
            
            if not logs: continue

            for line in logs.split('\n'):
                if not line: continue

                # Check for errors
                for pattern in error_patterns:
                    if pattern.search(line):
                        issue_key = f"global_pod_log_error/{namespace}/{pod_name}/{container_name}"
                        current_log_issues.add(issue_key)
                        
                        # Handle new error alerts
                        if issue_key not in ACTIVE_GLOBAL_POD_LOG_ALERTS:
                            subject = f"ERROR in Pod Log: {pod_name}/{container_name}"
                            body = (f"An error pattern was found in the logs of pod '{pod_name}' (container '{container_name}') in namespace '{namespace}'.\n"
                                    f"Pattern: '{pattern.pattern}'\nLog Line: '{line}'")
                            ALERT_BUFFER.append({"grouping_key": f"Global Pod Log Error:{namespace}", "subject": subject, "body": body, "severity": "ALERT"})
                            ACTIVE_GLOBAL_POD_LOG_ALERTS.add(issue_key)
                        
                        # Handle ongoing error alerts
                        elif ISSUE_ACTIVE_CYCLES.get(issue_key, 0) > 0 and (ISSUE_ACTIVE_CYCLES[issue_key] % ongoing_alert_cycles == 0):
                            subject = f"ONGOING ERROR in Pod Log: {pod_name}/{container_name}"
                            body = (f"An error pattern persists in the logs of pod '{pod_name}' (container '{container_name}') in namespace '{namespace}'.\n"
                                    f"Pattern: '{pattern.pattern}'\nLog Line: '{line}'\n"
                                    f"This issue has been ongoing for {ISSUE_ACTIVE_CYCLES[issue_key]} cycles.")
                            ALERT_BUFFER.append({"grouping_key": f"Global Pod Log Ongoing Error:{namespace}", "subject": subject, "body": body, "severity": "ONGOING"})
                        break # Found an error, move to next line/pattern

                # Check for warnings (only if no error was found in this line)
                else: # This 'else' belongs to the 'for pattern in error_patterns' loop
                    for pattern in warning_patterns:
                        if pattern.search(line):
                            issue_key = f"global_pod_log_warning/{namespace}/{pod_name}/{container_name}"
                            current_log_issues.add(issue_key)
                            
                            # Handle new warning alerts
                            if issue_key not in ACTIVE_GLOBAL_POD_LOG_ALERTS:
                                subject = f"WARNING in Pod Log: {pod_name}/{container_name}"
                                body = (f"A warning pattern was found in the logs of pod '{pod_name}' (container '{container_name}') in namespace '{namespace}'.\n"
                                        f"Pattern: '{pattern.pattern}'\nLog Line: '{line}'")
                                ALERT_BUFFER.append({"grouping_key": f"Global Pod Log Warning:{namespace}", "subject": subject, "body": body, "severity": "ALERT"}) # Changed to ALERT for initial
                                ACTIVE_GLOBAL_POD_LOG_ALERTS.add(issue_key)
                            
                            # Handle ongoing warning alerts
                            elif ISSUE_ACTIVE_CYCLES.get(issue_key, 0) > 0 and (ISSUE_ACTIVE_CYCLES[issue_key] % ongoing_alert_cycles == 0):
                                subject = f"ONGOING WARNING in Pod Log: {pod_name}/{container_name}"
                                body = (f"A warning pattern persists in the logs of pod '{pod_name}' (container '{container_name}') in namespace '{namespace}'.\n"
                                        f"Pattern: '{pattern.pattern}'\nLog Line: '{line}'\n"
                                        f"This issue has been ongoing for {ISSUE_ACTIVE_CYCLES[issue_key]} cycles.")
                                ALERT_BUFFER.append({"grouping_key": f"Global Pod Log Ongoing Warning:{namespace}", "subject": subject, "body": body, "severity": "ONGOING"})
                            break # Found a warning, move to next line/pattern
    
    # Update ISSUE_ACTIVE_CYCLES for current log issues
    for issue_key in current_log_issues:
        ISSUE_ACTIVE_CYCLES[issue_key] = ISSUE_ACTIVE_CYCLES.get(issue_key, 0) + 1

    # Handle resolved global pod log issues
    resolved_log_issues = ACTIVE_GLOBAL_POD_LOG_ALERTS - current_log_issues
    for issue_key in resolved_log_issues:
        _, namespace, pod_name, container_name = issue_key.split('/')[:4]
        issue_type = "Error" if "error" in issue_key else "Warning"
        subject = f"RESOLVED: {issue_type} in Pod Log: {pod_name}/{container_name}"
        body = f"The {issue_type.lower()} issue in logs for pod '{pod_name}' (container '{container_name}') in namespace '{namespace}' has been resolved."
        ALERT_BUFFER.append({"grouping_key": "Resolved", "subject": subject, "body": body, "severity": "RESOLVED"})
        ACTIVE_GLOBAL_POD_LOG_ALERTS.remove(issue_key)
        ISSUE_ACTIVE_CYCLES.pop(issue_key, None) # Remove from active cycles when resolved


def check_network_paths(config):
    global ACTIVE_NETWORK_PATH_ISSUES, ALERT_BUFFER
    network_config = config.get('network_path_monitoring', {})
    if not network_config.get('enabled'): return

    path_to_monitor = network_config.get('path')
    if not path_to_monitor: return

    print(f"K8s Watcher: Checking network path accessibility for '{path_to_monitor}'...")
    is_accessible, message = host_actions.check_path_accessibility(path_to_monitor)
    issue_key = f"network_path/{path_to_monitor}"

    if not is_accessible:
        if issue_key not in ACTIVE_NETWORK_PATH_ISSUES:
            subject = f"Network Path Inaccessible - '{path_to_monitor}'"
            body = f"The path '{path_to_monitor}' is inaccessible.\nReason: {message}"
            ALERT_BUFFER.append({"grouping_key": "Network Path Failure", "subject": subject, "body": body, "severity": "ALERT"})
            ACTIVE_NETWORK_PATH_ISSUES.add(issue_key)
    else:
        if issue_key in ACTIVE_NETWORK_PATH_ISSUES:
            subject = f"RESOLVED: Network Path Accessible - '{path_to_monitor}'"
            body = f"The path '{path_to_monitor}' is now accessible."
            ALERT_BUFFER.append({"grouping_key": "Resolved", "subject": subject, "body": body, "severity": "RESOLVED"})
            ACTIVE_NETWORK_PATH_ISSUES.remove(issue_key)

def run_k8s_checks(core_v1_api, apps_v1_api, custom_objects_api):
    global ALERT_BUFFER
    config, error = _load_watcher_config()
    if error:
        print(f"K8s Watcher Error: {error}")
        return
    if not config:
        print("K8s Watcher: Config is empty or invalid.")
        return
    
    interval = config.get('watcher_interval_seconds', 60)
    default_alert_action = config.get('default_alert_action', 'email')

    # Clear buffer at the start of each cycle
    ALERT_BUFFER = []

    # Run all checks, which will now populate the ALERT_BUFFER
    check_pod_statuses(core_v1_api, custom_objects_api, config)
    check_pod_logs(core_v1_api, config, interval)
    check_all_pod_logs(core_v1_api, config) # New global pod log monitoring
    check_network_paths(config)
    check_resource_usage(core_v1_api, custom_objects_api, config)
    check_deployment_health(core_v1_api, apps_v1_api, custom_objects_api, config)
    check_metrics_server_status(custom_objects_api, config) # Check metrics server status

    # Process the buffer to group and send alerts
    if ALERT_BUFFER:
        alerter.process_and_send_notifications(ALERT_BUFFER, alert_action=default_alert_action)