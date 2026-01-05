# Unified Monitor

A powerful, terminal-based monitoring tool designed for DevOps and Cloud Engineers to keep a close eye on Kubernetes clusters and their underlying host systems from a single interface.

## Overview

In modern cloud-native environments, observability is key. However, this often means juggling multiple tools and terminals: `kubectl` for Kubernetes resources, `top` or `htop` for host processes, `docker ps` for containers, and `tail` for logs.

The **Unified Monitor** brings these disparate views into a single, cohesive, and interactive terminal dashboard. It provides an at-a-glance overview of your entire stack—from the host machine's CPU to the status of individual pods—while also offering powerful, proactive monitoring and alerting capabilities.

## For the DevOps & Cloud Engineer

This tool is built to make your life easier by:

-   **Providing a Single Pane of Glass:** See Kubernetes events, pod status, and host-level metrics (CPU, Memory, Disk) side-by-side. This correlation is crucial for rapid troubleshooting. Did a pod just crash? Check the host's memory usage and system logs in the same tool without switching context.
-   **Reducing Tool Sprawl:** Stop jumping between `kubectl`, `docker`, `top`, and `journalctl`. The Unified Monitor provides a menu-driven interface to access the most common operational data.
-   **Enabling Proactive Monitoring:** Don't wait for your application to fail. The `--watch` mode runs as a daemon, continuously checking for abnormalities—like pods in a `CrashLoopBackOff` state or an excessive number of errors in system logs—and notifies you before they become critical incidents.
-   **Offering Deep Dives:** From the high-level dashboard, you can instantly jump into detailed views, stream logs from a specific pod, or even open an interactive shell inside a container for hands-on debugging.

## Key Features

-   **Live Interactive Dashboard:** A real-time overview of cluster and host health.
-   **Comprehensive K8s Views:** Inspect nodes, deployments, pods, services, configmaps, secrets, and more.
-   **Resource Usage:** View CPU and Memory consumption for deployments and individual pods.
-   **Host System Monitoring:** Track host CPU, memory, disk, running processes, Docker containers, and network statistics.
-   **Configurable Log Analysis:** Define rules in a YAML file to parse, highlight, and count keywords (like "ERROR", "WARN") in any host log file or command output.
-   **Watcher & Alerter Mode:** Run the tool as a background service to continuously monitor for issues and send email alerts when thresholds are breached.

## Getting Started

### Prerequisites

-   Python 3.8+
-   A configured `kubeconfig` file for cluster access.
-   Access to the host's logs and Docker socket (if applicable).

### Installation

1.  Clone the repository.
2.  Install the required Python packages:
    ```bash
    pip install -r requirements.txt
    ```

## How to Use

The application has two primary modes: **Interactive** and **Watcher**.

### Interactive Mode

This is the default mode, which launches the menu-driven terminal UI.

**To run:**

```bash
python3 -m src.main
```

You will be presented with a menu of options, including the main dashboard, detailed resource views, and host monitoring tools.

### Watcher Mode (`--watch`)

This mode runs the monitor as a continuous, non-interactive service. It's designed for automated monitoring and alerting.

**To run:**

```bash
python3 -m src.main --watch
```

In this mode, the application will:

1.  Periodically check the status of all pods in the cluster.
2.  Scan and analyze all log sources defined in `config.yml`.
3.  If a pod enters a failure state (e.g., `CrashLoopBackOff`, `ImagePullBackOff`) or if the number of errors in a log exceeds its configured threshold, it will trigger an alert.
4.  Alerts are sent via email to the configured stakeholders.

## Configuration

### Kubernetes Client

The tool uses the standard Kubernetes client discovery process. It will look for a `kubeconfig` file in the default location (`~/.kube/config`).

To specify a different `kubeconfig` file, set the `KUBECONFIG_PATH` environment variable:

```bash
export KUBECONFIG_PATH=/path/to/your/custom-kubeconfig.yaml
python3 -m src.main
```

### Host Log Monitoring

One of the most powerful features of the Unified Monitor is its ability to scrape and analyze logs from the host machine. This is configured in `config.yml`.

The configuration has two main sections: `logs` and `log_parsing_rules`.

#### 1. Defining Log Sources (`logs`)

You can define any number of log sources. A source can be a direct file path or the output of a shell command.

**Example `config.yml`:**

```yaml
logs:
  - display_name: "System Log"
    path: "/var/log/syslog"
  
  - display_name: "Authentication Log"
    path: "/var/log/auth.log"

  - display_name: "Docker Service Logs (last 50 lines)"
    command: "journalctl -u docker.service -n 50 --no-pager"
```

-   `display_name`: The friendly name that appears in the UI.
-   `path`: The absolute path to the log file to be read.
-   `command`: A shell command to execute. The tool will analyze its standard output.

#### 2. Defining Parsing Rules (`log_parsing_rules`)

These rules tell the monitor what to look for in the logs and how to classify it.

**Example `config.yml`:**

```yaml
log_parsing_rules:
  - name: "Errors"
    color: "red"
    threshold: 5
    keywords:
      - "error"
      - "err"
      - "failed"
      - "exception"
      - "traceback"

  - name: "Warnings"
    color: "yellow"
    threshold: 20
    keywords:
      - "warning"
      - "warn"
      - "timeout"
```

-   `name`: The name of the category (e.g., "Errors").
-   `color`: The color used to highlight these keywords in the interactive log viewer.
-   `threshold`: **Crucially, this is the value used by the Watcher.** If the number of keyword matches in a single check exceeds this threshold, an alert will be sent.
-   `keywords`: A list of case-insensitive strings to search for.

### Alerting Configuration

Alerts in watcher mode are sent via email. You must configure your SMTP server details using environment variables. Create a `.env` file in the project root or export these variables in your shell:

```
# .env file
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-email@example.com
SMTP_PASSWORD=your-email-password
EMAIL_SENDER=alerts@example.com
EMAIL_RECIPIENT=on-call-engineer@example.com
```
