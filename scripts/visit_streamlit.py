"""Open a Streamlit app in a browser so Community Cloud sees a real visit."""

import argparse
import re
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Visit a public Streamlit app once")
    parser.add_argument("url", help="Public https://...streamlit.app/ URL")
    args = parser.parse_args()

    parsed = urlparse(args.url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".streamlit.app"):
        parser.error("URL must be an HTTPS streamlit.app address")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            response = page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
            if response is None or response.status >= 400:
                raise RuntimeError(f"App visit failed: HTTP {response.status if response else 'no response'}")

            page.wait_for_function(
                """() => document.querySelector('iframe[title="streamlitApp"]') ||
                    document.body?.innerText.toLowerCase().includes('get this app back up')""",
                timeout=30_000,
            )
            wake_button = page.get_by_role("button", name=re.compile("get this app back up", re.I))
            if wake_button.is_visible():
                wake_button.click()

            app_frame = page.frame_locator('iframe[title="streamlitApp"]')
            app_frame.locator('[data-testid="stApp"]').wait_for(state="visible", timeout=90_000)
            print(f"Visited {args.url} and opened a Streamlit session")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
