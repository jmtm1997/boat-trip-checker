"""
Pembrokeshire Islands Boat Trips - Availability Checker
========================================================
Uses Selenium to load the FareHarbor booking calendar in a real
browser, wait for JavaScript to render, then reads available dates.

Credentials are read from environment variables (GitHub Secrets).
"""

import json
import smtplib
import os
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import urllib.request
import urllib.parse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================================================
# CONFIGURATION — read from environment variables (GitHub Secrets)
# ============================================================

GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_EMAIL_TO     = os.environ["ALERT_EMAIL_TO"]
PUSHOVER_USER_KEY  = os.environ["PUSHOVER_USER_KEY"]
PUSHOVER_API_TOKEN = os.environ["PUSHOVER_API_TOKEN"]

# Months to check — (year, month)
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
# SELENIUM BROWSER SETUP
# ============================================================

def make_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    return driver


# ============================================================
# AVAILABILITY CHECKING
# ============================================================

def check_month(driver, year, month):
    """
    Load the FareHarbor calendar for a given month and return
    a list of date strings (YYYY-MM-DD) that show as available (green).
    """
    url = (
        f"https://fareharbor.com/embeds/book/pembrokeshire-islands/items/291353/"
        f"calendar/{year}/{month:02d}/"
        f"?full-items=yes&back=https://www.pembrokeshire-islands.co.uk/boat-trips/"
        f"&flow=554483"
    )
    print(f"  Loading: {url}")
    driver.get(url)

    # Wait up to 20 seconds for the calendar to appear
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".fh-calendar, [class*='calendar'], table"))
        )
    except Exception:
        print("  [WARN] Timed out waiting for calendar — trying anyway")

    # Give JS a moment to fully render the date colours
    time.sleep(3)

    available_dates = []

    # FareHarbor marks available days with an 'available' class on the cell.
    # Try several selector patterns to be robust across widget versions.
    selectors = [
        "td.available",
        "td[class*='available']",
        "div[class*='available']",
        "button[class*='available']",
        "[data-available='true']",
        ".CalendarMonth_day--highlighted",
    ]

    for selector in selectors:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        if elements:
            print(f"  Found {len(elements)} available element(s) with selector: {selector}")
            for el in elements:
                # Try to get the date from common attributes
                for attr in ["data-date", "data-day", "aria-label", "title"]:
                    val = el.get_attribute(attr)
                    if val and len(val) >= 10:
                        # Extract YYYY-MM-DD if present
                        import re
                        match = re.search(r'(\d{4}-\d{2}-\d{2})', val)
                        if match:
                            available_dates.append(match.group(1))
                            break
                        # Try parsing a date like "28" from the cell text + known year/month
                        text = el.text.strip()
                        if text.isdigit() and 1 <= int(text) <= 31:
                            available_dates.append(f"{year}-{month:02d}-{int(text):02d}")
                            break
                else:
                    # No date attribute — use cell text if it's a day number
                    text = el.text.strip()
                    if text.isdigit() and 1 <= int(text) <= 31:
                        available_dates.append(f"{year}-{month:02d}-{int(text):02d}")
            break  # Stop trying selectors once one works

    # Deduplicate and sort
    result = sorted(set(available_dates))
    return result


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
