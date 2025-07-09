import os
import requests
import dns.resolver
import dns.exception
import time
import json
import subprocess
from datetime import datetime
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HOSTS = ["xxx.xxx.xx", "xxx.xxx.xx", "xxx.xxx.xx", "xxx.xxx.xx"]
EMAIL = "<--e-MAIL-->"
EMAIL_SECONDARY = "<--e-MAIL-->"
LOG_FILE = os.path.expanduser("~/neighbor_monitor.log")
STATUS_FILE = os.path.expanduser("~/neighbor_monitor_status.current")
CURL_TIMEOUT = 10
SLEEP_INTERVAL = 120
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '<--TOKEN-->')
SENDER_EMAIL_API = os.environ.get('SENDER_EMAIL_API', '<--e-MAIL-->')
SENDGRID_API_ENDPOINT = "https://api.sendgrid.com/v3/mail/send"
SENDGRID_API_HOSTNAME = "api.sendgrid.com"
PUSHBULLET_TOKEN = os.environ.get('PUSHBULLET_TOKEN', '<--TOKEN-->')
PB_API_BASE_URL = "https://api.pushbullet.com/v2/pushes"
PB_API_HOSTNAME = "api.pushbullet.com"
GOOGLE_DNS_SERVERS = ['8.8.8.8', '8.8.4.4']

def log_message(message):
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.now()}: {message}\n")

def resolve_hostname_custom_dns(hostname, dns_servers):
    resolved_ip = None
    log_message(f"Attempting to resolve {hostname} using custom DNS servers: {dns_servers}...")
    try:
        custom_resolver = dns.resolver.Resolver(configure=False)
        custom_resolver.nameservers = dns_servers
        custom_resolver.timeout = 2
        custom_resolver.lifetime = 5
        answers = custom_resolver.resolve(hostname, 'A')
        resolved_ip = str(answers[0].address)
        log_message(f"Successfully resolved {hostname} to {resolved_ip} using custom DNS.")
    except dns.resolver.NXDOMAIN:
        log_message(f"DNS Error: Domain '{hostname}' does not exist according to {dns_servers}")
    except dns.exception.Timeout:
        log_message(f"DNS Error: Query for '{hostname}' timed out when using {dns_servers}")
    except dns.exception.DNSException as e:
        log_message(f"DNS Error: An unexpected DNS error occurred for '{hostname}': {e}")
    except Exception as e:
        log_message(f"An unexpected error occurred during DNS resolution for '{hostname}': {e}")
    return resolved_ip

def check_https(host):
    resolved_ip = resolve_hostname_custom_dns(host, GOOGLE_DNS_SERVERS)
    if not resolved_ip:
        log_message(f"Could not resolve IP for {host}. HTTPS check skipped.")
        return "HTTPS_FAIL(DNS_FAIL)"
    url_with_ip = f"https://{resolved_ip}/"
    headers = {"Host": host}
    try:
        response = requests.head(
            url_with_ip,
            headers=headers,
            timeout=CURL_TIMEOUT,
            verify=False
        )
        if 200 <= response.status_code < 500:
            return f"HTTPS_OK({response.status_code})"
        else:
            return f"HTTPS_FAIL({response.status_code})"
    except requests.exceptions.Timeout:
        return "HTTPS_FAIL(TIMEOUT)"
    except requests.exceptions.ConnectionError as e:
        return f"HTTPS_FAIL(CONN_ERROR: {e})"
    except requests.exceptions.RequestException as e:
        return f"HTTPS_FAIL(REQUEST_ERROR: {e})"
    except Exception as e:
        log_message(f"An unexpected error occurred during HTTPS check for {host} ({resolved_ip}): {e}")
        return "HTTPS_FAIL(EXCEPTION)"

def send_api_email(recipient_email, subject, body):
    resolved_sg_ip = resolve_hostname_custom_dns(SENDGRID_API_HOSTNAME, GOOGLE_DNS_SERVERS)
    if not resolved_sg_ip:
        log_message(f"Failed to resolve SendGrid API hostname. Email to {recipient_email} not sent.")
        return False
    api_url_with_ip = f"https://{resolved_sg_ip}/v3/mail/send"
    json_payload = {
        "personalizations": [
            {
                "to": [
                    {
                        "email": recipient_email
                    }
                ]
            }
        ],
        "from": {
            "email": SENDER_EMAIL_API
        },
        "subject": subject,
        "content": [
            {
                "type": "text/plain",
                "value": body
            }
        ]
    }
    headers = {
        "Host": SENDGRID_API_HOSTNAME,
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(
            api_url_with_ip,
            headers=headers,
            json=json_payload,
            verify=False,
            timeout=CURL_TIMEOUT
        )
        response.raise_for_status()
        log_message(f"API Email sent successfully to {recipient_email} with subject '{subject}'")
        return True
    except requests.exceptions.HTTPError as err:
        log_message(f"HTTP Error sending email to {recipient_email}: {err}. Response: {err.response.text}")
        return False
    except requests.exceptions.RequestException as err:
        log_message(f"Request Error sending email to {recipient_email}: {err}")
        return False
    except Exception as e:
        log_message(f"An unexpected error occurred sending email to {recipient_email}: {e}")
        return False

def send_pushbullet_notification(title, body):
    resolved_pb_ip = resolve_hostname_custom_dns(PB_API_HOSTNAME, GOOGLE_DNS_SERVERS)
    if not resolved_pb_ip:
        log_message("Failed to resolve Pushbullet API hostname. Pushbullet notification not sent.")
        return False
    api_url_with_ip = f"https://{resolved_pb_ip}/v2/pushes"
    payload = {
        "type": "note",
        "title": title,
        "body": body
    }
    headers = {
        "Host": PB_API_HOSTNAME,
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(
            api_url_with_ip,
            auth=(PUSHBULLET_TOKEN, ''),
            json=payload,
            headers=headers,
            verify=False,
            timeout=CURL_TIMEOUT
        )
        response.raise_for_status()
        log_message(f"Pushbullet notification sent successfully with title '{title}'")
        return True
    except requests.exceptions.HTTPError as err:
        log_message(f"HTTP Error sending Pushbullet: {err}. Response: {err.response.text}")
        return False
    except requests.exceptions.RequestException as err:
        log_message(f"Request Error sending Pushbullet: {err}")
        return False
    except Exception as e:
        log_message(f"An unexpected error occurred sending Pushbullet: {e}")
        return False

def main():
    log_message("Script started.")
    host_status = {host: "UNKNOWN" for host in HOSTS}

    while True:
        log_message("Starting new monitoring cycle...")
        previous_overall_status = "UNKNOWN"
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, "r") as f:
                    previous_overall_status = f.read().strip()
            except Exception as e:
                log_message(f"Error reading status file: {e}. Assuming UNKNOWN status.")
                previous_overall_status = "UNKNOWN"
        else:
            log_message(f"Status file '{STATUS_FILE}' not found. Initializing with 'OK'.")
            with open(STATUS_FILE, "w") as f:
                f.write("OK")
            previous_overall_status = "OK"

        current_failures = 0
        for host in HOSTS:
            https_status = check_https(host)
            host_status[host] = f"HTTPS: {https_status}"
            if "FAIL" in https_status:
                current_failures += 1

        current_overall_status = "OK"
        if current_failures > 0:
            current_overall_status = "FAIL"

        report = "Neighbor Host Status Report\n"
        report += f"{datetime.now()}\n\n"
        for host in HOSTS:
            report += f"• {host}: {host_status[host]}\n"

        log_message(report)

        if current_overall_status != previous_overall_status:
            log_message(f"Status changed from {previous_overall_status} to {current_overall_status}. Sending notifications.")
            send_api_email(EMAIL, f"[STATUS CHANGE] Neighbor Host - From {previous_overall_status} to {current_overall_status}", report)
            send_api_email(EMAIL_SECONDARY, "[ALERT] System Issues on HTTPD ALL", "HTTPD MONITOR ALERT FROM ALL")
            pb_title = f"Host Monitor Alert: {current_overall_status}"
            pb_body = f"Status changed from {previous_overall_status} to {current_overall_status}.\n\n{report}"
            send_pushbullet_notification(pb_title, pb_body)
            with open(STATUS_FILE, "w") as f:
                f.write(current_overall_status)
        else:
            log_message(f"Status remains {current_overall_status}. No new notification sent.")

        log_message(f"Monitoring cycle finished. Sleeping for {SLEEP_INTERVAL} seconds...")
        time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    main()
