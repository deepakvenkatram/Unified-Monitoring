# Unified Monitor

A powerful, terminal-based monitoring tool designed for developers, DevOps, and Cloud Engineers to keep a close eye on Kubernetes clusters and their underlying host systems from a single, simple interface.

## What is This?

In modern cloud environments, keeping track of everything is complicated. You might use one command to check your application's pods, another to see the server's CPU usage, and yet another to read log files.

The **Unified Monitor** simplifies this by bringing all that information into one place. It's a single tool that gives you an "at-a-glance" overview of your entire system's health, from the host machine's memory to the status of individual applications running in Kubernetes.

It has two main modes:
1.  **Interactive Mode:** A user-friendly, menu-driven dashboard in your terminal that you can use to manually explore your system.
2.  **Watcher Mode:** A 24/7 automated monitor that runs in the background, watches for problems, and sends you an email alert when something goes wrong.

---

## Key Features

### For Everyone
- **Simple Menu Interface:** No complex commands to remember. Just run the tool and pick an option from the menu.
- **All-in-One Dashboard:** See the most important health metrics for both the host server and the Kubernetes cluster on a single screen.

### Kubernetes Monitoring
- **View Cluster Health:** Check the status of all nodes in your cluster.
- **Application Status:** See if your applications (Deployments and Pods) are running correctly.
- **Live Resource Usage:** See how much CPU and Memory your applications are using.
- **Read Logs:** Easily view the logs from any running application pod without needing `kubectl`.
- **Interactive Shell:** Open a command-line shell directly inside a running container for advanced debugging.
- **Simple Management:** Scale your applications (increase/decrease copies) or update a container's image directly from the menu.

### Host Server Monitoring
- **System Health:** View live CPU, Memory, and Disk usage.
- **Process Explorer:** See which programs are using the most resources on the server.
- **Docker Support:** List all running Docker containers.
- **Log Viewer:** Read and analyze any system log file (e.g., `/var/log/syslog`). The tool can even highlight important keywords like "ERROR" or "WARNING" for you.

### Automated Alerting (Watcher Mode)
- **Pod Failure Alerts:** Automatically get an email if an application pod crashes or enters a failure state (like `CrashLoopBackOff` or `ImagePullBackOff`).
- **Log-Based Alerts:** Configure the watcher to read logs and send an email if it finds too many error messages in a short period.
- **Termination Auditing:** If the monitoring script is stopped, it logs which user stopped it and from which IP address, providing a basic audit trail.

---

## Getting Started: A Step-by-Step Guide

Follow these steps to get the Unified Monitor running on your machine.

### Step 1: Prerequisites (What you need first)

You only need two things to run this tool:
1.  **Python (Version 3.8 or newer):** This program is written in Python.
2.  **A Kubernetes Config File:** This is a special file that allows the tool to connect to your Kubernetes cluster. It's usually located at `~/.kube/config`.

To check if you have Python, open your terminal and run:
```bash
python3 --version
```
If this shows a version like `Python 3.8.10` or higher, you're all set. If not, you will need to install Python first.

### Step 2: Download and Install

1.  **Clone the project:**
    ```bash
    git clone https://github.com/your-repo/ks-monitoring-ansible.git
    cd ks-monitoring-ansible
    ```

2.  **Install the dependencies:**
    This single command installs all the helper packages the tool needs.
    ```bash
    pip install -r requirements.txt
    ```

### Step 3: Run the Interactive Dashboard!

You're ready to go! To start the application in its interactive menu mode, run:
```bash
python3 -m src.main --mode interactive
```
You should see the main menu. From here, you can explore all the features!

---

## Configuration (For Advanced Features)

To enable features like email alerts, you need to provide some configuration. This is done with two files: `.env` and `config.yml`.

### The `.env` File (for Secrets)

This file holds sensitive information, like passwords for email.

1.  **Create the file:** Copy the example file to create your own.
    ```bash
    cp .env.example .env
    ```

2.  **Edit the file:** Open the new `.env` file in a text editor and fill in the details.
    - **For Email Alerts (Watcher Mode):** You must fill in the `SMTP_*` variables. This tells the tool how to connect to your email server to send alerts.
    - `TERMINATION_EMAIL_RECIPIENT`: A separate email address (or comma-separated list) specifically for notifications when the monitoring application starts or terminates.
    - **For Identifying the Server:** It's highly recommended to set the `ENVIRONMENT_NAME`. This name will be included in the subject line of all email alerts, helping you immediately identify which server the alert came from (e.g., "[Production] Pod 'xyz' is crashing").
      ```dotenv
      # Example for using a Gmail account
      # Note: You may need to create an "App Password" in your Google account settings.
      ENVIRONMENT_NAME="Production"
      SMTP_HOST=smtp.gmail.com
      SMTP_PORT=587
      SMTP_USER=your_email@gmail.com
      SMTP_PASSWORD=your_gmail_app_password
      EMAIL_SENDER=your_email@gmail.com
      EMAIL_RECIPIENT=email_to_receive_alerts@example.com
      ```

### The `config.yml` File (for Behavior)

This file controls *how* the monitor behaves, especially in Watcher mode. You can open `config.yml` and edit it to change these settings.

**Key Settings:**
-   `watcher_interval_seconds`: How often the watcher checks for problems (e.g., `60` means once every minute).
-   `ongoing_alert_cycles`: How often to re-send an alert for a problem that hasn't been fixed (e.g., `20` means it will send a reminder every 20 cycles).
-   `pod_alert_statuses`: A list of pod statuses (e.g., `CrashLoopBackOff`) that will trigger an email alert.
-   `resource_usage_monitoring`: Proactively alerts if a pod's CPU or Memory usage exceeds a percentage of its defined limit.
    -   `enabled`: Set to `true` to activate this feature.
    -   `cpu_threshold_percent`: The percentage of the CPU limit that triggers an alert (e.g., 90).
    -   `memory_threshold_percent`: The percentage of the Memory limit that triggers an alert (e.g., 90).
-   `deployment_health_monitoring`: Proactively alerts about deployment issues like stuck rollouts or insufficient available replicas.
    -   `enabled`: Set to `true` to activate this feature.
    -   `unavailable_replicas_threshold`: The number of unavailable replicas that triggers an alert (0 means any unavailable replica).
    -   `stuck_rollout_timeout_seconds`: How long (in seconds) a deployment can be stuck in a rollout before an alert is triggered.
-   `global_pod_log_scanning`: Scans the latest logs of *all* pods for predefined error and warning patterns.
    -   `enabled`: Set to `true` to activate this feature.
    -   `lines_to_scan`: The number of recent log lines to fetch from each container.
    -   `include_namespaces`: (Optional) A list of specific namespaces to include in the scan. If empty, all namespaces are considered (subject to `exclude_namespaces`).
    -   `exclude_namespaces`: (Optional) A list of specific namespaces to exclude from the scan. These take precedence over `include_namespaces`.
    -   `error_patterns`: A list of regex patterns to identify critical errors.
    -   `warning_patterns`: A list of regex patterns to identify warnings or potential issues.
-   `pod_log_monitoring`: (Watcher mode only) Rules for scanning pod logs for errors.

---

## How to Run in Watcher Mode

To run the tool as a background service that automatically monitors your system and sends alerts, use the `watcher` mode.

**Important:** You must configure your `.env` file with email settings for alerts to work!

**To start the watcher:**
```bash
python3 -m src.main --mode watcher
```
The tool will now run in the background. You can close your terminal. It will send an email if it detects any issues based on your `config.yml` rules. To stop it, you will need to find its process ID and use the `kill` command.

When the watcher is stopped gracefully, it will log the event to `alerts.log`, noting the user and IP address for security.

### How to Stop the Watcher

Stopping a background process on Linux involves two steps: finding its Process ID (PID) and then using the `kill` command.

**1. Find the Process ID (PID)**

Run the following command in your terminal:
```bash
ps aux | grep "python3 -m src.main"
```
You will see an output like this:
```
your_user  12345  0.5  1.2 ... python3 -m src.main --mode watcher
your_user  12347  0.0  0.0 ... grep "python3 -m src.main"
```
The PID is the number in the second column for the line that is **not** the `grep` command. In this example, the PID is `12345`.

**2. Stop the Process**

Use the `kill` command with the PID you just found. This will stop the script gracefully and trigger the final termination log.
```bash
kill 12345
```
### The Example-Deployment Directory
The directory has a couple of yaml manifiest files that would create resources in default namepsace, these yaml file will create pods and writes logs as erros, warning etc, the broken deployment would create a pod in error status. Use these example to try and implement the configuration that you might want the application to monitor.

The memory hog manifest file simple create a pod with less resources and stimulates a OMMKILLED error.

### Using Ansible to run and host this script on servers

  Prerequisites

   1. Ansible Installed: Make sure you have Ansible installed on the machine where you are running the commands.
   2. SSH Access: You need to have SSH access to the target monitoring host(s) from your control machine (where you're running Ansible). You should be able to SSH into the target machine
      without a password, preferably using SSH keys.
   3. Inventory File: You need an inventory file (like the inventory.ini file we discussed) that lists the IP addresses or hostnames of the servers where you want to deploy the
      monitoring script.

  Steps to Deploy

   1. Define Your Inventory:

      Open the inventory.ini file and replace <192.168.64.1> with the actual IP address or hostname of your target server. If you have multiple servers, you can add them under the
  [monitoring_hosts] group, one per line.

   1     [monitoring_hosts]
   2     your_server_ip_or_hostname

   2. Configure SSH Access (if needed):

      If you haven't set up passwordless SSH access to your target server, you'll need to add connection variables to your inventory file. For example:

   1     [monitoring_hosts]
   2     your_server_ip_or_hostname ansible_user=your_username ansible_ssh_private_key_file=~/.ssh/my_aws_key.pem

      Note: Storing passwords in plain text is not recommended for security reasons. Using SSH keys is the best practice.

   3. Run the Ansible Playbook:

      Open your terminal and run the following command from the root of the project directory (/home/deepak/ks-monitering-ansible):

   1     ansible-playbook -i inventory.ini deploy.yml

      This command will:
       * Connect to the host(s) specified in inventory.ini.
       * Execute the tasks defined in deploy.yml, which include:
           * Installing Python.
           * Copying the project files to /opt/unified-monitor on the remote server.
           * Installing the required Python packages.
           * Starting the main.py script in watcher mode in the background.

   4. Verify the Deployment:

      After the playbook has finished running, you can SSH into your target server to verify that the script is running.

       * Check for the process:
   1         ps aux | grep "src.main --mode watcher"
          You should see a process running the Python script.

       * Check the log file:
          The script's output is redirected to /opt/unified-monitor/watcher.log. You can view the logs with:
   1         tail -f /opt/unified-monitor/watcher.log

**As a last resort**, if the process does not stop, you can force it to terminate with `kill -9 <PID>`. Note that this method will prevent the script from logging the termination event.
