"""
Pembrokeshire Islands Boat Trips - Availability Checker
========================================================
Checks FareHarbor booking pages for June & July 2026 availability
and sends email + Pushover (SMS/push) alerts when slots open up.

Credentials are read from environment variables so they never
appear in the code — safe to use with GitHub Actions.
"""

import urllib.request
import urllib.parse
import json
import smtplib
import os
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ============================================================
# CONFIGURATION — read from environment variables (set these
# as GitHub Secrets, never hard-code passwords in the script)
# ============================================================

GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_EMAIL_TO     = os.environ["ALERT_EMAIL_TO"]
PUSHOVER_USER_KEY  = os.environ["PUSHOVER_USER_KEY"]
PUSHOVER_API_TOKEN = os.environ["PUSHOVER_API_TOKEN"]

# Months to monitor (year, month) — June and July 2026
MONTHS_TO_CHECK = [
    (2026, 6),
    (2026, 7),
]

# FareHarbor company and item
COMPANY = "pembrokeshire-islands"
ITEM_ID = "291353"

# File to track which dates we've already alerted about (avoids duplicate alerts)
STATE_FILE = "alerted_dates.json"

# ============================================================
# CORE FUNCTIONS
# ============================================================

def load_alerted_dates():
    """Load the set of dates we've already sent alerts for."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_alerted_dates(alerted):
    """Save the updated set of alerted dates."""
    with open(STATE_FILE, "w") as f:
        json.dump(list(alerted), f)


def fetch_calendar_page(year, month):
    """
    Fetch the FareHarbor embed calendar page for a given month.
    Returns the raw HTML, or None on error.
    """
    url = (
        f"https://fareharbor.com/embeds/book/{COMPANY}/items/{ITEM_ID}"
        f"/calendar/{year}/{month:02d}/"
        f"?full-items=yes&back=https://www.pembrokeshire-islands.co.uk/boat-trips/"
        f"&flow=554483"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [ERROR] Could not fetch {year}-{month:02d}: {e}")
        return None


def find_available_dates(html, year, month):
    """
    Parse the calendar HTML to find dates that have availability.
    FareHarbor marks available days with CSS classes like 'has-availabilities'
    or similar. We also look for date strings in JSON data blobs.
    Returns a list of date strings like ['2026-06-14', '2026-06-21'].
    """
    available = []

    # Strategy 1: look for data-date attributes on elements with availability markers
    # FareHarbor uses patterns like: data-date="2026-06-14" ... available
    date_pattern = re.compile(
        r'data-date=["\'](\d{4}-\d{2}-\d{2})["\'][^>]*class=["\'][^"\']*available',
        re.IGNORECASE
    )
    for match in date_pattern.finditer(html):
        available.append(match.group(1))

    # Strategy 2: reverse — class first, then data-date nearby
    block_pattern = re.compile(
        r'class=["\'][^"\']*available[^"\']*["\'][^>]*data-date=["\'](\d{4}-\d{2}-\d{2})["\']',
        re.IGNORECASE
    )
    for match in block_pattern.finditer(html):
        available.append(match.group(1))

    # Strategy 3: look for JSON availability data embedded in the page
    # FareHarbor often embeds availability as a JS object
    json_date_pattern = re.compile(
        r'"date"\s*:\s*"(\d{4}-' + f'{month:02d}' + r'-\d{2})"'
    )
    for match in json_date_pattern.finditer(html):
        available.append(match.group(1))

    # Deduplicate and filter to the correct month
    prefix = f"{year}-{month:02d}-"
    seen = set()
    result = []
    for d in available:
        if d.startswith(prefix) and d not in seen:
            seen.add(d)
            result.append(d)

    return sorted(result)


def send_email(subject, body):
    """Send an alert email via Gmail."""
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
    """Send a push notification via Pushover."""
    try:
        data = urllib.parse.urlencode({
            "token":   PUSHOVER_API_TOKEN,
            "user":    PUSHOVER_USER_KEY,
            "title":   title,
            "message": message,
            "url":     f"https://fareharbor.com/embeds/book/{COMPANY}/items/{ITEM_ID}/calendar/2026/06/?full-items=yes&back=https://www.pembrokeshire-islands.co.uk/boat-trips/&flow=554483",
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
    """Send both email and push notification for newly available dates."""
    date_list = "\n".join(f"  • {d}" for d in sorted(new_dates))
    booking_url = (
        "https://fareharbor.com/embeds/book/pembrokeshire-islands/items/291353/"
        "calendar/2026/06/?full-items=yes"
        "&back=https://www.pembrokeshire-islands.co.uk/boat-trips/&flow=554483"
    )

    subject = f"🚤 Pembrokeshire boat trip tickets available! ({len(new_dates)} date(s))"
    body = (
        f"Good news! Tickets have become available for the following date(s):\n\n"
        f"{date_list}\n\n"
        f"Book here:\n{booking_url}\n\n"
        f"(This alert was sent at {datetime.now().strftime('%Y-%m-%d %H:%M')})"
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

    for year, month in MONTHS_TO_CHECK:
        print(f"\nChecking {year}-{month:02d}...")
        html = fetch_calendar_page(year, month)
        if not html:
            continue

        available = find_available_dates(html, year, month)

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
