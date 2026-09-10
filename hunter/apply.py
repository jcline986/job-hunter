from __future__ import annotations

import json
from pathlib import Path

from hunter.config import CONTACT_PATH

LINKEDIN_HOSTS = ("linkedin.com", "lnkd.in")


def _contact() -> dict:
    return json.loads(CONTACT_PATH.read_text())


def is_linkedin(url: str) -> bool:
    host = (url or "").lower()
    return any(part in host for part in LINKEDIN_HOSTS)


def apply_in_browser(url: str, resume_path: str, cover_note: str) -> None:
    """Open the application page, fill obvious fields, then wait for you to submit."""
    if is_linkedin(url):
        raise RuntimeError(
            "LinkedIn Easy Apply automation is not supported (it violates LinkedIn's terms). "
            "Open the listing yourself and upload the tailored resume."
        )

    from playwright.sync_api import sync_playwright

    contact = _contact()
    resume = str(Path(resume_path).resolve())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)

        def fill_first(selectors: list[str], value: str) -> None:
            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if locator.count() and locator.is_visible():
                        locator.fill(value, timeout=1500)
                        return
                except Exception:
                    continue

        fill_first(
            [
                "input[name='first_name']",
                "input[name='firstName']",
                "input[autocomplete='given-name']",
                "input[aria-label*='First name' i]",
            ],
            contact["first_name"],
        )
        fill_first(
            [
                "input[name='last_name']",
                "input[name='lastName']",
                "input[autocomplete='family-name']",
                "input[aria-label*='Last name' i]",
            ],
            contact["last_name"],
        )
        fill_first(
            [
                "input[type='email']",
                "input[name='email']",
                "input[autocomplete='email']",
            ],
            contact["email"],
        )
        fill_first(
            [
                "input[type='tel']",
                "input[name='phone']",
                "input[autocomplete='tel']",
            ],
            contact["phone_display"],
        )

        for selector in [
            "input[type='file']",
            "input[name='resume']",
            "input[accept*='pdf']",
            "input[accept*='word']",
        ]:
            locator = page.locator(selector).first
            try:
                if locator.count():
                    locator.set_input_files(resume, timeout=2000)
                    break
            except Exception:
                continue

        for selector in [
            "textarea[name='cover_letter']",
            "textarea[id*='cover' i]",
            "textarea[aria-label*='cover' i]",
            "textarea[name='comments']",
        ]:
            locator = page.locator(selector).first
            try:
                if locator.count() and locator.is_visible():
                    locator.fill(cover_note, timeout=2000)
                    break
            except Exception:
                continue

        page.pause()
        context.close()
        browser.close()
