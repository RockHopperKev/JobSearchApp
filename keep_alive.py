import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

APP_URL = os.environ.get("APP_URL", "").strip()
APP_MARKER = "Tailored Resume Builder"  # text that appears once the app has loaded
MAX_WAIT_SECONDS = 240  # a cold start can take a couple of minutes
HOLD_SECONDS = 30  # stay connected briefly so the visit registers as real activity


def app_is_loaded(page):
    # Streamlit Community Cloud may render the app inside an iframe,
    # so check every frame on the page.
    for frame in page.frames:
        try:
            if frame.get_by_text(APP_MARKER).count() > 0:
                return True
        except Exception:
            continue
    return False


def main():
    if not APP_URL:
        print("APP_URL is not set. Add the STREAMLIT_APP_URL repository secret.")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(8)

        wake = page.get_by_role("button", name=re.compile("get this app back up", re.I))
        if wake.count() > 0:
            print("App was asleep. Clicking the wake button...")
            wake.first.click()
        else:
            print("No wake button found; the app appears to be awake.")

        deadline = time.time() + MAX_WAIT_SECONDS
        while time.time() < deadline:
            if app_is_loaded(page):
                print("App loaded. Holding the session briefly...")
                time.sleep(HOLD_SECONDS)
                print("Done.")
                browser.close()
                return
            time.sleep(5)

        print("App did not load within the time limit.")
        page.screenshot(path="failure.png")
        browser.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
