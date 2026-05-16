"""
Pembrokeshire Islands Boat Trips - Availability Checker
========================================================
Uses Chrome DevTools Protocol (CDP) to intercept the network
requests FareHarbor's own JavaScript makes to fetch availability,
then reads the response data directly.

Credentials are read from environment variables (GitHub Secrets).
"""

import json
import smtplib
import os
import time
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import urllib.request
import urllib.parse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# ============================================================
# CONFIGURATION
# ============================================================

GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_EMAIL_TO     = os.environ["ALERT_EMAIL_TO"]
PUSHOVER_USER_KEY  = os.environ["PUSHOVER_USER_KEY"]
PUSHOVER_API_TOKEN = os.environ["PUSHOVER_API_TOKEN"]

MONTHS_TO_CHECK = [
    (2026, 6),
    (2026, 7),
]

BOOKING_URL = (
    "https://fareharbor.com/embeds/book/pembrokeshire-islands/items/291353/"
    "calendar/2026/06/?full-items=yes"
    "&back=https://www.pembrokeshire-islands.co.uk/boat-trips/&flow=554483"
)

STATE_FILE = "alerted_dates.json"

# ============================================================
# BROWSER SETUP WITH NETWORK LOGGING
# ============================================================

def make_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    # Enable performance logging to capture network requests
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)
    # Enable CDP network tracking
    driver.execute_cdp_cmd("Network.enable", {})
    return driver


def get_network_responses(driver):
    """Extract all network response URLs and bodies from performance logs."""
    logs = driver.get_log("performance")
    responses = []
    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            if msg.get("method") == "Network.responseReceived":
                url = msg["params"]["response"]["url"]
                request_id = msg["params"]["requestId"]
                responses.append((url, request_id))
        except Exception:
            pass
    return responses


def get_response_body(driver, request_id):
    """Get the response body for a given request ID via CDP."""
    try:
        result = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        return result.get("body", "")
    except Exception:
        return ""


# ============================================================
# AVAILABILITY CHECKING
# ============================================================

def check_month(driver, year, month):
    url = (
        f"https://fareharbor.com/embeds/book/pembrokeshire-islands/items/291353/"
        f"calendar/{year}/{month:02d}/"
        f"?full-items=yes&back=https://www.pembrokeshire-islands.co.uk/boat-trips/"
        f"&flow=554483"
    )
    print(f"  Loading: {url}")

    # Clear logs before loading
    driver.get("about:blank")
    time.sleep(1)
    driver.get_log("performance")  # flush old logs

    driver.get(url)

    # Wait for the page to make its API calls
    print("  Waiting for API calls to complete...")
    time.sleep(15)

    # Scan all network requests for availability data
    responses = get_network_responses(driver)
    print(f"  Captured {len(responses)} network responses")

    available_dates = []

    for resp_url, request_id in responses:
        # Look for FareHarbor availability API calls
        if "availabilit" in resp_url.lower() or ("fareharbor" in resp_url and "item" in resp_url):
            print(f"  Interesting URL: {resp_url}")
            body = get_response_body(driver, request_id)
            if body:
                print(f"  Response body (first 500 chars): {body[:500]}")
                try:
                    data = json.loads(body)
                    # Extract available dates from the response
                    availabilities = data.get("availabilities", [])
                    for a in availabilities:
                        capacity = a.get("capacity", 0)
                        start_at = a.get("start_at", "")
                        if capacity > 0 and start_at:
                            day = start_at[:10]
                            available_dates.append(day)
                            print(f"    Available: {day} (capacity: {capacity})")
                except json.JSONDecodeError:
                    pass

    # Also print ALL captured URLs for debugging if nothing found
    if not available_dates:
        print("  No availability found in intercepted requests.")
        print("  All captured URLs:")
        for resp_url, _ in responses[:30]:
            print(f"    {resp_url}")

    return sorted(set(available_dates))


# ============================================================
# ALERTS
# ============================================================

def load_alerted_dates():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_alerted_dates(alerted):
    with open(STATE_FILE, "w") as f:
        json.dump(list(alerted), f)


def send_email(subject, body):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = ALERT_EMAIL_TO
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, ALERT_EMAIL_TO, msg.as_string())
        print("  [OK] Email sent.")
    except Exception as e:
        print(f"  [ERROR] Email failed: {e}")


def send_pushover(title, message):
    try:
        data = urllib.parse.urlencode({
            "token":     PUSHOVER_API_TOKEN,
            "user":      PUSHOVER_USER_KEY,
            "title":     title,
            "message":   message,
            "url":       BOOKING_URL,
            "url_title": "Book now",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.pushover.net/1/messages.json",
            data=data,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("status") == 1:
                print("  [OK] Pushover notification sent.")
            else:
                print(f"  [ERROR] Pushover error: {result}")
    except Exception as e:
        print(f"  [ERROR] Pushover failed: {e}")


def send_alert(new_dates):
    date_list = "\n".join(f"  • {d}" for d in sorted(new_dates))
    subject = f"🚤 Pembrokeshire boat trip tickets available! ({len(new_dates)} date(s))"
    body = (
        f"Good news! Tickets are now available for the following date(s):\n\n"
        f"{date_list}\n\n"
        f"Book here:\n{BOOKING_URL}\n\n"
        f"(Alert sent at {datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )
    print(f"  Sending alerts for: {', '.join(sorted(new_dates))}")
    send_email(subject, body)
    send_pushover(
        "🚤 Boat trip tickets available!",
        f"{len(new_dates)} date(s) open: {', '.join(sorted(new_dates))}"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"\n=== Availability check started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    alerted_dates = load_alerted_dates()
    newly_found = set()

    driver = make_driver()
    try:
        for year, month in MONTHS_TO_CHECK:
            print(f"\nChecking {year}-{month:02d}...")
            available = check_month(driver, year, month)
            if available:
                print(f"  Found available dates: {available}")
                for d in available:
                    if d not in alerted_dates:
                        newly_found.add(d)
            else:
                print(f"  No availability found.")
    finally:
        driver.quit()

    if newly_found:
        print(f"\nNew dates found — sending alerts...")
        send_alert(newly_found)
        alerted_dates.update(newly_found)
        save_alerted_dates(alerted_dates)
    else:
        print("\nNo new availability. No alerts sent.")

    print("=== Check complete ===\n")


if __name__ == "__main__":
    main()
