import os
import smtplib
import ssl
import getpass
import psutil
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime
from rich.console import Console
from rich.markdown import Markdown
from collections import defaultdict

# --- Global State ---
SMTP_CONFIG_CHECKED = False
SMTP_IS_CONFIGURED = False
FAILED_EMAIL_ATTEMPTS = []
MAX_FAILED_EMAIL_RECORDS = 5
ALERT_LOG_FILE_PATH = "./alerts.log"
ONGOING_ISSUES_LOG_FILE_PATH = "./ongoing_issues.log"

# --- Configuration and Logging ---

def _check_smtp_configuration():
    global SMTP_CONFIG_CHECKED, SMTP_IS_CONFIGURED
    if SMTP_CONFIG_CHECKED: return SMTP_IS_CONFIGURED
    
    smtp_vars = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_SENDER", "EMAIL_RECIPIENT"]
    missing_vars = [var for var in smtp_vars if not os.getenv(var)]

    if missing_vars:
        print(f"Warning: SMTP not configured. Missing: {', '.join(missing_vars)}. Email alerts disabled.")
        SMTP_IS_CONFIGURED = False
    else:
        SMTP_IS_CONFIGURED = True
    
    SMTP_CONFIG_CHECKED = True
    return SMTP_IS_CONFIGURED

def log_alert_to_file(subject, body):
    try:
        with open(ALERT_LOG_FILE_PATH, 'a') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] Subject: {subject}\nBody:\n{body}\n" + "-"*80 + "\n")
        if "Program Started" not in subject and "Program Terminated" not in subject:
            print(f"Alert logged to {ALERT_LOG_FILE_PATH}")
        return True
    except Exception as e:
        print(f"Error logging alert to file: {e}")
        return False

def log_program_start():
    subject = "Program Started"
    body = f"Unified Monitor started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
    log_alert_to_file(subject, body)
    
    # Send email notification for start-up
    termination_recipients = os.getenv('TERMINATION_EMAIL_RECIPIENT')
    if termination_recipients:
        _send_email_internal(subject, body, recipient_override=termination_recipients)

def log_program_termination():
    try: user = getpass.getuser()
    except: user = "unknown"
    
    ip_address = "N/A"
    if ssh_conn := os.getenv('SSH_CONNECTION'):
        ip_address = ssh_conn.split()[0]

    try:
        process = psutil.Process(os.getpid())
        mem_usage_mb = process.memory_info().rss / (1024 * 1024)
        memory_usage_str = f"{mem_usage_mb:.2f} MB"
    except:
        memory_usage_str = "N/A"
    
    subject = "Program Terminated"
    body = (f"User: {user}\nSource IP: {ip_address}\n"
            f"Termination Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Final Memory Usage: {memory_usage_str}")
    log_alert_to_file(subject, body)
    
    # Send email notification for termination
    termination_recipients = os.getenv('TERMINATION_EMAIL_RECIPIENT')
    if termination_recipients:
        _send_email_internal(subject, body, recipient_override=termination_recipients)
    print("\nProgram termination logged.")

# --- Email Sending Logic ---

def _send_email_internal(subject, body, recipient_override=None):
    global FAILED_EMAIL_ATTEMPTS
    if not _check_smtp_configuration(): return False

    if FAILED_EMAIL_ATTEMPTS:
        body += "\n\n--- Previous Email Sending Failures ---\n" + "\n".join(
            f"[{i+1}] Failed to send '{f['subject']}' at {f['timestamp']}. Error: {f['error']}"
            for i, f in enumerate(FAILED_EMAIL_ATTEMPTS)
        )
        FAILED_EMAIL_ATTEMPTS = []

    # --- Determine Recipients ---
    if recipient_override:
        recipient_emails = [addr.strip() for addr in recipient_override.split(',') if addr.strip()]
    else:
        recipient_email_str = os.getenv("EMAIL_RECIPIENT")
        if not recipient_email_str:
            print("Error: EMAIL_RECIPIENT environment variable is not set.")
            return False
        recipient_emails = [addr.strip() for addr in recipient_email_str.split(',') if addr.strip()]

    if not recipient_emails:
        print("Error: No valid recipient email addresses found.")
        return False

    # --- Create Email Structure ---
    message = MIMEMultipart('related')
    env_name = os.getenv('ENVIRONMENT_NAME', 'Default')
    final_subject = f"[{env_name}] {subject}"
    message["Subject"] = final_subject
    message["From"] = os.getenv("EMAIL_SENDER")
    message["To"] = ", ".join(recipient_emails) # Use the determined recipients
    
    msg_alternative = MIMEMultipart('alternative')
    message.attach(msg_alternative)

    # --- Determine Header Color ---
    header_color = "#2c3e50" # Default
    if subject.strip().startswith("RESOLVED"): header_color = "#27ae60" # Green
    elif subject.strip().startswith("ALERT"): header_color = "#c0392b" # Red
    elif subject.strip().startswith("ONGOING"): header_color = "#f39c12" # Orange

    # --- Generate HTML Body ---
    try:
        with open("src/email_template.html", "r") as f: html_template = f.read()
        
        console = Console(record=True, width=100)
        console.print(Markdown(body))
        body_html = console.export_html(inline_styles=True)

        teams_share_text = f"**Environment: {env_name}**\n**Alert: {subject}**\n\n---\n\n{body}"
        teams_url = f"https://teams.microsoft.com/share?msgText={urllib.parse.quote(teams_share_text)}"
        teams_button_html = f'''
            <a href="{teams_url}" target="_blank" style="background-color: #6165f5; color: #ffffff; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: inline-block; font-size: 14px; font-weight: bold;">
                Share Alert in Teams
            </a>
        '''

        html_part = html_template.replace("{{HEADER_COLOR}}", header_color)
        html_part = html_part.replace("{{SHARE_IN_TEAMS_BUTTON}}", teams_button_html)
        html_part = html_part.replace("{{BODY_CONTENT}}", body_html)
        html_part = html_part.replace("{{TIMESTAMP}}", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        msg_alternative.attach(MIMEText(body, "plain"))
        msg_alternative.attach(MIMEText(html_part, "html"))
    except Exception as e:
        print(f"Warning: Could not generate HTML email content: {e}")
        msg_alternative.attach(MIMEText(body, "plain"))

    # --- Embed Logo ---
    try:
        with open('logo.jpeg', 'rb') as f:
            img = MIMEImage(f.read(), 'jpeg')
            img.add_header('Content-ID', '<logo_image>')
            message.attach(img)
    except FileNotFoundError: pass # Silently fail if no logo
    except Exception as e: print(f"Warning: Could not embed logo: {e}")

    # --- Send Email ---
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT"))) as server:
            server.starttls(context=context)
            server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"))
            server.sendmail(os.getenv("EMAIL_SENDER"), recipient_emails, message.as_string()) # Use determined recipients
        print(f"Email notification sent for: {subject}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        FAILED_EMAIL_ATTEMPTS.append({"subject": subject, "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "error": str(e)})
        return False

# --- Main Alert Processing Function ---

def process_and_send_notifications(alert_buffer, alert_action="email"):
    if not alert_buffer: return
    if alert_action == "log_file":
        for alert in alert_buffer:
            log_alert_to_file(alert["subject"], alert["body"])
        return

    # --- Grouping Logic ---
    grouped_alerts = defaultdict(list)
    for alert in alert_buffer:
        grouped_alerts[alert["grouping_key"]].append(alert)

    # --- Process and Send Each Group ---
    for group_key, alerts in grouped_alerts.items():
        if len(alerts) == 1:
            # If only one alert in a group, send it as a single notification
            alert = alerts[0]
            subject_prefix = "ALERT: " if alert["severity"] == "ALERT" else f"{alert['severity']}: "
            _send_email_internal(f"{subject_prefix}{alert['subject']}", alert['body'])
        else:
            # If multiple alerts, create a summarized notification
            severity = alerts[0]['severity']
            subject_prefix = f"ALERT: " if severity == "ALERT" else f"{severity}: "
            
            # Example: "High CPU Usage:default" -> "High CPU Usage in 'default' namespace"
            group_title = group_key.replace(":", " in namespace ")
            
            subject = f"{len(alerts)} {group_title} issues detected"
            
            body = f"## {subject_prefix}{subject}\n\n"
            body += "The following related issues were detected in this cycle:\n\n"
            # Define newline_indent once outside the loop for f-string compatibility
            newline_indent = '\n   - '
            for i, alert in enumerate(alerts):
                body += f"**{i+1}. {alert['subject']}**\n"
                body += "   - " + alert['body'].replace('\n', newline_indent) + "\n\n"
            
            _send_email_internal(f"{subject_prefix}{subject}", body)
