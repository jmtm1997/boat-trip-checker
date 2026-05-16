"""
Pembrokeshire Islands Boat Trips - Availability Checker
========================================================
Waits for Angular to finish rendering the calendar before
reading available dates.

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
# BROWSER SETUP
# ============================================================

def make_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    driver = webdriver.Chrome(options=options)
    return driver


# ============================================================
# WAIT FOR ANGULAR TO FINISH RENDERING
# ============================================================

def wait_for_angular(driver, timeout=30):
    """
    Wait until Angular has finished rendering by checking that:
    1. The ng-cloak class has been removed from the html element
    2. At least one <td> has a non-empty class (meaning availability colours applied)
    """
    # First wait for ng-cloak to be removed (Angular's signal that it's bootstrapped)
    try:
        WebDriverWait(driver, timeout).until_not(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[ng-cloak], .ng-cloak"))
        )
        print("  Angular bootstrapped (ng-cloak removed)")
    except Exception:
        print("  Timed out waiting for ng-cloak removal — continuing anyway")

    # Then wait until at least one td has a class (availability colours applied)
    print("  Waiting for availability colours to render...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        tds = driver.find_elements(By.TAG_NAME, "td")
        classes_found = [td.get_attribute("class") for td in tds if td.get_attribute("class")]
        if classes_found:
            print(f"  Calendar rendered — found td classes: {classes_found[:5]}")
            return True
        time.sleep(1)

    print("  Timed out waiting for calendar colours — dumping td classes for debug:")
    tds = driver.find_elements(By.TAG_NAME, "td")
    for td in tds[:10]:
        print(f"    text={td.text.strip()!r} class={td.get_attribute('class')!r}")
    return False


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
    driver.get(url)

    rendered = wait_for_angular(driver, timeout=45)

    available_dates = []

    # Dump all td classes so we can see exactly what FareHarbor uses
    tds = driver.find_elements(By.TAG_NAME, "td")
    print(f"  Total td elements: {len(tds)}")
    unique_classes = set()
    for td in tds:
        cls = td.get_attribute("class") or ""
        if cls:
            unique_classes.add(cls)

    if unique_classes:
        print(f"  Unique td classes found: {unique_classes}")
    else:
        print("  No td classes found at all — Angular may not have rendered")

    # Look for available dates using JavaScript to inspect the Angular scope
    # FareHarbor's Angular app stores availability data in the page's JS scope
    try:
        result = driver.execute_script("""
            // Try to find availability data in Angular scope or window variables
            var results = [];

            // Check window for any fh or fareharbor variables
            for (var key in window) {
                if (key.toLowerCase().includes('avail') || key.toLowerCase().includes('fh')) {
                    try {
                        results.push(key + ': ' + JSON.stringify(window[key]).substring(0, 200));
                    } catch(e) {}
                }
            }

            // Also try to get Angular scope data from the root element
            try {
                var el = document.querySelector('[ng-app], [data-ng-app]');
                if (el) {
                    var scope = angular.element(el).scope();
                    results.push('angular_scope_keys: ' + JSON.stringify(Object.keys(scope)));
                }
            } catch(e) {
                results.push('angular_scope_error: ' + e.message);
            }

            return results;
        """)
        print(f"\n  JS scope data: {result[:10]}")
    except Exception as e:
        print(f"  JS execution error: {e}")

    # Try reading available dates from td background colour via JS
    try:
        coloured_tds = driver.execute_script("""
            var results = [];
            var tds = document.querySelectorAll('td');
            tds.forEach(function(td) {
                var style = window.getComputedStyle(td);
                var bg = style.backgroundColor;
                var cls = td.className;
                var txt = td.innerText.trim();
                if (txt && txt.match(/^\\d+$/)) {
                    results.push({text: txt, bg: bg, cls: cls});
                }
            });
            return results;
        """)
        print(f"\n  TD colour data (first 10): {coloured_tds[:10]}")

        # Green background = available. FareHarbor uses approximately rgb(34, 139, 34) or similar
        for td_data in coloured_tds:
            bg = td_data.get('bg', '')
            txt = td_data.get('text', '')
            cls = td_data.get('cls', '')
            # Print all so we can see what colours are used
            print(f"    day={txt} bg={bg} cls={cls}")

    except Exception as e:
        print(f"  Colour detection error: {e}")

    return available_dates


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
                print(f"  No availability detected yet.")
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
