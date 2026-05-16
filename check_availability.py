"""
Pembrokeshire Islands Boat Trips - Availability Checker (DEBUG VERSION)
=======================================================================
This version dumps the page HTML and all calendar-related elements
so we can see exactly what CSS classes FareHarbor uses for available dates.
"""

import json
import os
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# We still need secrets present even in debug mode
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_EMAIL_TO     = os.environ["ALERT_EMAIL_TO"]
PUSHOVER_USER_KEY  = os.environ["PUSHOVER_USER_KEY"]
PUSHOVER_API_TOKEN = os.environ["PUSHOVER_API_TOKEN"]

URL = (
    "https://fareharbor.com/embeds/book/pembrokeshire-islands/items/291353/"
    "calendar/2026/07/"
    "?full-items=yes&back=https://www.pembrokeshire-islands.co.uk/boat-trips/"
    "&flow=554483"
)

def make_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    driver = webdriver.Chrome(options=options)
    return driver


def main():
    print(f"\n=== DEBUG run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"Loading: {URL}\n")

    driver = make_driver()
    try:
        driver.get(URL)

        # Wait for any table or div to appear
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "table"))
            )
            print(">> Table element found in page")
        except Exception:
            print(">> No table found after 20s")

        # Extra wait for JS rendering
        time.sleep(5)

        # Print the page title
        print(f"\nPage title: {driver.title}")

        # Dump ALL td elements and their classes
        print("\n--- All <td> elements and their classes ---")
        tds = driver.find_elements(By.TAG_NAME, "td")
        print(f"Total <td> elements found: {len(tds)}")
        for td in tds[:50]:  # limit to first 50
            cls = td.get_attribute("class") or ""
            txt = td.text.strip()
            attrs = {}
            for attr in ["data-date", "data-day", "aria-label", "title", "data-available"]:
                val = td.get_attribute(attr)
                if val:
                    attrs[attr] = val
            if cls or txt:
                print(f"  text={repr(txt):<6} class={repr(cls):<60} attrs={attrs}")

        # Also dump any elements with 'green' or 'available' in their class
        print("\n--- Elements with 'available' in class ---")
        try:
            els = driver.find_elements(By.XPATH, "//*[contains(@class,'available')]")
            print(f"Found {len(els)} elements with 'available' in class")
            for el in els[:20]:
                print(f"  tag={el.tag_name} class={repr(el.get_attribute('class'))} text={repr(el.text.strip())}")
        except Exception as e:
            print(f"  Error: {e}")

        # Dump a snippet of the raw HTML around the calendar
        print("\n--- Raw HTML snippet (first 3000 chars) ---")
        html = driver.page_source
        print(html[:3000])

    finally:
        driver.quit()

    print("\n=== DEBUG complete ===")


if __name__ == "__main__":
    main()
