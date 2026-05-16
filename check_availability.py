"""
Pembrokeshire Islands Boat Trips - Availability Checker
========================================================
Checks FareHarbor's API directly for June & July 2026 availability
and sends email + Pushover alerts when slots open up.

Credentials are read from environment variables (GitHub Secrets).
"""

import urllib.request
import urllib.parse
import json
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ============================================================
# CONFIGURATION — read from environment variables (GitHub Secrets)
# ============================================================

GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_EMAIL_TO     = os.environ["ALERT_EMAIL_TO"]
PUSHOVER_USER_KEY  = os.environ["PUSHOVER_USER_KEY"]
PUSHOVER_API_TOKEN = os.environ["PUSHOVER_API_TOKEN"]

# FareHarbor details (extracted from the booking URL)
COMPANY = "pembrokeshire-islands"
ITEM_ID = "291353"

# Date ranges to monitor — (start_date, end_date) as strings YYYY-MM-DD
DATE_RANGES = [
    ("2026-06-01", "2026-06-30"),
    ("2026-07-01", "2026-07-31"),
]

# Booking URL to include in alerts
BOOKING_URL = (
    "https://fareharbor.com/embeds/book/pembrokeshire-islands/items/291353/"
    "calendar/2026/06/?full-items=yes"
    "&back=https://www.pembrokeshire-islands.co.uk/boat-trips/&flow=554483"
)

# File to track which dates we've already alerted about
STATE_FILE = "alerted_dates.json"

# ============================================================
# CORE FUNCTIONS
# ============================================================

def load_alerted_dates():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_alerted_dates(alerted):
    with open(STATE_FILE, "w") as f:
        json.dump(list(alerted), f)


def fetch_availabilities(start_date, end_date):
    """
    Query FareHarbor's availability API for a date range.
    This is the same endpoint the booking widget uses to show green/grey dates.
    Returns a list of availability objects, or empty list on error.
    """
    url = (
        f"https://fareharbor.com/api/external/v1/companies/{COMPANY}/"
        f"items/{ITEM_ID}/availabilities/date-range/{start_date}/{end_date}/"
        f"?flow=554483"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://fareharbor.com/embeds/book/pembrokeshire-islands/",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("availabilities", [])
    except Exception as e:
        print(f"  [ERROR] Could not fetch {start_date} to {end_date}: {e}")
        return []


def extract_available_dates(availabilities):
    """
    From a list of availability objects, return dates that have capacity > 0.
    Each availability has a 'start_at' like '2026-07-28T09:00:00+01:00'
    and 'capacity' for remaining spots.
    """
    available_dates = set()
    for a in availabilities:
        capacity = a.get("capacity", 0)
        start_at = a.get("start_at", "")
        if capacity > 0 and start_at:
            day = start_at[:10]  # e.g. '2026-07-28'
            available_dates.add(day)
    return sorted(available_dates)


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

    for start_date, end_date in DATE_RANGES:
        print(f"\nChecking {start_date} to {end_date}...")
        availabilities = fetch_availabilities(start_date, end_date)

        if availabilities is None:
            continue

        available = extract_available_dates(availabilities)

        if available:
            print(f"  Found available dates: {available}")
            for d in available:
                if d not in alerted_dates:
                    newly_found.add(d)
        else:
            print(f"  No availability found.")

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
