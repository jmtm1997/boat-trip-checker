"""
Pembrokeshire Islands Boat Trips - Availability Checker
========================================================
Calls FareHarbor's internal calendar API directly — no browser needed.
Fast, lightweight, and uses very few GitHub Actions minutes.

Credentials are read from environment variables (GitHub Secrets).
"""

import json
import smtplib
import os
import urllib.request
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_EMAIL_TO     = os.environ["ALERT_EMAIL_TO"]
PUSHOVER_USER_KEY  = os.environ["PUSHOVER_USER_KEY"]
PUSHOVER_API_TOKEN = os.environ["PUSHOVER_API_TOKEN"]

# Months to fetch from the API
MONTHS_TO_CHECK = [
    (2026, 5),
    (2026, 6),
    (2026, 7),
]

# Only alert on these specific dates
DATES_TO_WATCH = set(
    # Specific May dates
    ["2026-05-22", "2026-05-23", "2026-05-24", "2026-05-30", "2026-05-31"]
    # All of June
    + [f"2026-06-{d:02d}" for d in range(1, 31)]
    # July 1st to 26th
    + [f"2026-07-{d:02d}" for d in range(1, 27)]
)

BOOKING_URL = (
    "https://fareharbor.com/embeds/book/pembrokeshire-islands/items/291353/"
    "calendar/2026/05/?full-items=yes"
    "&back=https://www.pembrokeshire-islands.co.uk/boat-trips/&flow=554483"
)

# ============================================================
# AVAILABILITY CHECKING
# ============================================================

def fetch_available_dates(year, month):
    """
    Call FareHarbor's internal calendar API for a given month.
    Returns a list of date strings (YYYY-MM-DD) that are bookable.
    """
    url = (
        f"https://fareharbor.com/api/v1/companies/pembrokeshire-islands/"
        f"items/291353/calendar/{year}/{month:02d}/"
        f"?allow_grouped=yes&bookable_only=no&asn=&path=1&is_fh_app=no"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://fareharbor.com/embeds/book/pembrokeshire-islands/",
        "Accept": "application/json",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [ERROR] Could not fetch {year}-{month:02d}: {e}")
        return []

    available_dates = []
    weeks = data.get("calendar", {}).get("weeks", [])
    for week in weeks:
        for day in week.get("days", []):
            if day.get("month") != "current":
                continue
            date_str = day.get("at", "")
            count = day.get("count", 0)
            is_bookable = day.get("is_bookable", False)

            if count > 0 and is_bookable and date_str in DATES_TO_WATCH:
                available_dates.append(date_str)
                print(f"  Available: {date_str} ({count} slot(s))")

    return available_dates


# ============================================================
# ALERTS
# ============================================================

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


def send_alert(dates):
    date_list = "\n".join(f"  • {d}" for d in sorted(dates))
    subject = f"🚤 Pembrokeshire boat trip tickets available! ({len(dates)} date(s))"
    body = (
        f"Good news! Tickets are now available for the following date(s):\n\n"
        f"{date_list}\n\n"
        f"Book here:\n{BOOKING_URL}\n\n"
        f"(Alert sent at {datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )
    print(f"  Sending alerts for: {', '.join(sorted(dates))}")
    send_email(subject, body)
    send_pushover(
        "🚤 Boat trip tickets available!",
        f"{len(dates)} date(s) open: {', '.join(sorted(dates))}"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"\n=== Availability check started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    found = set()

    for year, month in MONTHS_TO_CHECK:
        print(f"\nChecking {year}-{month:02d}...")
        available = fetch_available_dates(year, month)
        if available:
            for d in available:
                found.add(d)
        else:
            print(f"  No availability found.")

    if found:
        print(f"\nDates found — sending alerts...")
        send_alert(found)
    else:
        print("\nNo availability. No alerts sent.")

    print("=== Check complete ===\n")


if __name__ == "__main__":
    main()
