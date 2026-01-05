import time
import yaml
from pathlib import Path
from . import k8s_actions, host_actions, alerter, k8s_watcher

# In-memory state to track sent alerts and avoid spam
# Format: {'alert_key': timestamp_of_last_alert}
# Example key: 'log/syslog/Errors'
ALERT_STATE = {}
# Cooldown in seconds before re-alerting for the same issue if it resolves and reappears
ALERT_COOLDOWN = 3600  # 1 hour

def _load_watcher_config():
    """Loads watcher-specific configurations from config.yml."""
    config_file = Path("config.yml")
    if not config_file.is_file():
        return None, "Configuration file not found."
    
    with open(config_file, 'r') as f:
        try:
            config = yaml.safe_load(f)
            interval = config.get('watcher_interval_seconds', 60)
            return interval, None
        except yaml.YAMLError as e:
            return None, f"Error parsing YAML file: {e}"

def _can_send_alert(key):
    """Checks if an alert for a given key is allowed based on state and cooldown."""
    last_alert_time = ALERT_STATE.get(key)
    if last_alert_time:
        if time.time() - last_alert_time < ALERT_COOLDOWN: 
            return False  # Still in cooldown
    return True

def _update_alert_state(key):
    """Updates the state for a given alert key with the current timestamp."""
    ALERT_STATE[key] = time.time()

def check_log_thresholds(config):
    """Checks all configured logs and appends alerts to the buffer if thresholds are breached."""
    print("Watcher: Checking host log thresholds...")
    log_configs, error = host_actions.load_log_config()
    if error:
        print(f"Watcher Error: Could not load log config: {error}")
        return

    for log_entry in log_configs:
        _, summary, err = host_actions.get_log_output(log_entry)
        if err:
            print(f"Watcher Error: Could not process log '{log_entry['display_name']}': {err}")
            continue
        
        for rule_name, data in summary.items():
            if data['count'] >= data['threshold']:
                alert_key = f"log/{log_entry['display_name']}/{rule_name}"
                if _can_send_alert(alert_key):
                    subject = f"ALERT: Log threshold breached for '{rule_name}' in '{log_entry['display_name']}'"
                    body = (
                        f"A log threshold has been breached.\n\n"
                        f"Log Source: {log_entry['display_name']}\n"
                        f"Rule: {rule_name}\n"
                        f"Count: {data['count']}\n"
                        f"Threshold: {data['threshold']}\n"
                    )
                    k8s_watcher.ALERT_BUFFER.append({"type": "host_log", "severity": "ALERT", "subject": subject, "body": body})
                    _update_alert_state(alert_key)

def start_watcher():
    """Main function to start the continuous monitoring loop."""
    print("Starting Unified Monitor in Watcher mode...")
    
    interval, error = _load_watcher_config()
    if error:
        print(f"Fatal Error: {error}. Exiting watcher.")
        return

    print(f"Check interval set to {interval} seconds.")

    # Initialize Kubernetes clients
    core_v1_api, apps_v1_api, custom_objects_api = k8s_actions.init_clients()
    if not all([core_v1_api, apps_v1_api, custom_objects_api]):
        print("Fatal Error: Failed to initialize Kubernetes clients. Exiting watcher.")
        return

    # Load main config for watcher
    main_config, config_error = k8s_watcher._load_watcher_config()
    if config_error:
        print(f"Fatal Error: Could not load main watcher config: {config_error}. Exiting watcher.")
        return

    while True:
        try:
            # Run Kubernetes checks
            # All clients are passed here
            k8s_watcher.run_k8s_checks(core_v1_api, apps_v1_api, custom_objects_api)

            # Run host-level checks
            check_log_thresholds(main_config)
            
            print(f"Watcher: Cycle complete. Sleeping for {interval} seconds...")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nWatcher stopped by user. Exiting.")
            break
        except Exception as e:
            print(f"An unexpected error occurred in the watcher loop: {e}")
            print("Restarting checks in 60 seconds...")
            time.sleep(60)
