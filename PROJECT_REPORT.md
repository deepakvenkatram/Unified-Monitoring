# Unified Monitor: Project Report

## 1. Introduction

The Unified Monitor is a powerful and flexible monitoring tool designed for DevOps and Cloud Engineers to keep a close watch on their Kubernetes clusters and the underlying host systems. It provides a comprehensive solution for monitoring, alerting, and debugging, all from a single, easy-to-use interface.

This tool is built with Python and can be run in two modes:

*   **Interactive Mode:** A rich terminal-based UI that provides a dashboard and a wide range of options to explore and manage your Kubernetes and host resources.
*   **Watcher Mode:** A non-interactive mode that runs in the background, continuously monitoring your systems and sending alerts when issues are detected.

This report provides a detailed overview of the Unified Monitor, its features, how to deploy and configure it, and why it can be a more reliable and efficient solution than other monitoring tools.

## 2. Key Features

The Unified Monitor is packed with features to provide a comprehensive monitoring experience.

### 2.1. Interactive Mode

The interactive mode provides a rich and user-friendly terminal interface with the following capabilities:

*   **Unified Dashboard:** A single pane of glass that displays the status of your Kubernetes cluster and host system in real-time.
*   **Kubernetes Monitoring:**
    *   View Node Information
    *   List All Namespaces
    *   View Services
    *   Stream Cluster Events
    *   View Resource Quotas
    *   View Pod Status & Usage
    *   View Deployment Status & Usage
    *   View Pod Logs
    *   Open Interactive Pod Shell
    *   Scale a Deployment
    *   Edit a Deployment
    *   View Persistent Volumes
    *   View Persistent Volume Claims
    *   View ConfigMaps
    *   View Secrets
    *   View Resource YAML
    *   Describe K8s Resource
*   **Host Monitoring:**
    *   View Host Resource Usage
    *   View Process Explorer
    *   View Docker Containers
    *   View Host System Logs
    *   View Network Stats

### 2.2. Watcher Mode

The watcher mode runs as a background service and provides the following monitoring and alerting capabilities:

*   **Pod Status Monitoring:** Monitors pods for critical statuses like `CrashLoopBackOff`, `ImagePullBackOff`, `OOMKilled`, `Error`, and `Failed`.
*   **Pod Log Monitoring:** Scans pod logs for specific error patterns and triggers alerts based on a configurable threshold and time window.
*   **Network Path Monitoring:** Monitors the accessibility of a specified network path and sends an alert if it becomes unreachable.
*   **Host Log Monitoring:** Monitors host-level log files for specific keywords and triggers alerts based on a configurable threshold.
*   **Advanced Alerting:**
    *   **HTML Email Alerts:** Sends beautifully formatted HTML email alerts with detailed information about the issue.
    *   **Alert Digest:** Groups all alerts within a monitoring cycle into a single digest email to avoid alert fatigue.
    *   **Ongoing Issue Notifications:** Sends periodic notifications for issues that persist for a configurable number of cycles.
    *   **Resolved Notifications:** Sends notifications when an issue is resolved.
    *   **Alert Logging:** Logs all alerts to a file for auditing and historical analysis.
    *   **Ongoing Issue Logging:** Logs repeating errors to a separate file, even if an email is not sent, to maintain a complete record of all issues.
    *   **Program Termination Logging:** Logs when the program is terminated and by which user.

## 3. Why Unified Monitor? (In-house vs. Other Tools)

While there are many excellent open-source and commercial monitoring tools available, the Unified Monitor offers several unique advantages, especially as an in-house tool:

*   **Tailor-Made for Your Needs:** As an in-house tool, it is designed and built to meet the specific needs of your organization. It can be easily customized and extended to monitor your unique infrastructure and applications.
*   **Simplicity and Ease of Use:** The Unified Monitor is designed to be simple to deploy, configure, and use. The `config.yml` file provides a single place to manage all your monitoring configurations, and the interactive mode is intuitive and easy to navigate.
*   **No Extra Overhead:** Unlike some larger monitoring solutions that require their own complex infrastructure, the Unified Monitor is a lightweight Python application that can be deployed on any server with Python and Ansible.
*   **Cost-Effective:** As an in-house tool, there are no licensing fees or subscription costs. You have complete control over the tool and its development.
*   **Enhanced Security:** By keeping your monitoring tool in-house, you have greater control over its security and can ensure that it complies with your organization's security policies.
*   **Deep Integration:** The tool is designed to be deeply integrated with your environment. The ability to execute commands, view logs, and interact with your Kubernetes cluster directly from the tool provides a seamless and efficient workflow for DevOps and Cloud Engineers.

## 4. Getting Started

### 4.1. Prerequisites

*   Python 3
*   pip
*   Ansible
*   Access to a Kubernetes cluster

### 4.2. Deployment with Ansible

The Unified Monitor can be easily deployed to your monitoring servers using the provided Ansible playbook.

1.  **Inventory:** Update the `inventory.ini` file with the hostnames or IP addresses of your monitoring servers.

    ```ini
    [monitoring_hosts]
    your-server-ip
    ```

2.  **Configuration:**
    *   Create a `.env` file with your SMTP server details for email alerting. You can use the `.env.example` file as a template.
    *   Update the `config.yml` file with your desired monitoring configurations.

3.  **Deploy:** Run the `deploy.yml` playbook to deploy the Unified Monitor to your servers.

    ```bash
    ansible-playbook -i inventory.ini deploy.yml
    ```

The playbook will perform the following tasks:

*   Install Python 3 and pip.
*   Create a deployment directory on the remote server.
*   Copy the project files to the remote server.
*   Install the required Python dependencies.
*   Copy the `.env` and `config.yml` files to the remote server.
*   Start the monitor in watcher mode as a background process.

## 5. Configuration

The Unified Monitor is configured using the `config.yml` file. This file allows you to customize the behavior of the watcher and the interactive mode.

### 5.1. Watcher Configuration

*   `watcher_interval_seconds`: How often the watcher should check for issues, in seconds.
*   `ongoing_alert_cycles`: The number of cycles an issue must be active before an "ongoing issue" email is sent. An email will be sent every time the cycle count is a multiple of this value.
*   `default_alert_action`: The default action for alerts. Can be `email`, `log_file`, or `both`.

### 5.2. Pod Status Monitoring

*   `pod_alert_statuses`: A list of pod statuses that will trigger an alert in watcher mode.

### 5.3. Pod Log Monitoring

*   `pod_log_monitoring.enabled`: Enable or disable pod log monitoring.
*   `pod_log_monitoring.tail_lines`: The number of recent log lines to scan in each check.
*   `pod_log_monitoring.targets`: A list of monitoring rules for different sets of pods. Each target can have:
    *   `name`: A descriptive name for the target.
    *   `namespace`: The namespace to monitor.
    *   `label_selector`: A label selector to filter pods.
    *   `error_patterns`: A list of regex patterns to search for.
    *   `threshold`: The number of matches that must be found within the `time_window` to trigger an alert.
    *   `time_window`: The time window to count errors in (e.g., '10m', '1h').

### 5.4. Network Path Monitoring

*   `network_path_monitoring.enabled`: Enable or disable network path monitoring.
*   `network_path_monitoring.path`: The file system path to monitor.
*   `network_path_monitoring.email_on_unreachable`: Whether to send an email if the path is unreachable.

### 5.5. Host Log Monitoring

*   `logs`: A list of log sources for the interactive menu. Each log source can be defined by a `path` to a log file or a `command` to execute.
*   `log_parsing_rules`: Rules for parsing and color-coding log files in the interactive menu.

## 6. Usage

### 6.1. Interactive Mode

To run the Unified Monitor in interactive mode, simply run the `main.py` script without any arguments:

```bash
python3 -m src.main
```

This will launch the interactive menu, where you can choose from a wide range of options to monitor and manage your Kubernetes and host resources.

### 6.2. Watcher Mode

To run the Unified Monitor in watcher mode, use the `--mode watcher` argument:

```bash
python3 -m src.main --mode watcher
```

The watcher will run in the background, continuously monitoring your systems and sending alerts based on the configurations in `config.yml`.

## 7. Conclusion

The Unified Monitor is a powerful and versatile tool that can significantly streamline the monitoring and debugging process for DevOps and Cloud Engineers. Its flexibility, ease of use, and deep integration capabilities make it a valuable asset for any organization looking to improve its monitoring posture. As an in-house tool, it can be continuously adapted and improved to meet the evolving needs of your infrastructure and applications, making it a more reliable and efficient solution than many off-the-shelf monitoring tools.
