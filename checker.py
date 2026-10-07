import asyncio
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


BASE_URL = "https://lbv-termine.de/frontend/"
FUEHRERSCHEIN_URL = BASE_URL + "dienstleistungsauswahl.php?kategorieid=1"

# This is the LBV location used in the user's appointment page.
# It avoids the fragile text click on the location card.
APPOINTMENT_URL = BASE_URL + "terminauswahl.php?standortid=109"

# Alert only for appointments strictly before 02.12.2026.
TARGET_DATE = date(2026, 12, 2)

STATE_FILE = Path(".state/last_alert.txt")

MONTHS = {
    "Januar": 1,
    "Februar": 2,
    "März": 3,
    "April": 4,
    "Mai": 5,
    "Juni": 6,
    "Juli": 7,
    "August": 8,
    "September": 9,
    "Oktober": 10,
    "November": 11,
    "Dezember": 12,
}


def log(message: str) -> None:
    print(f"[LBV] {message}", flush=True)


def today_berlin() -> date:
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def read_state() -> str:
    if STATE_FILE.exists():
        return STATE_FILE.read_text(encoding="utf-8").strip()
    return "NONE"


def write_state(value: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(value, encoding="utf-8")


def send_telegram(message: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()


async def goto_lbv(page, url: str, wait_ms: int = 2500) -> None:
    try:
        await page.goto(url, wait_until="commit", timeout=30000)
    except PlaywrightTimeoutError as exc:
        # LBV can keep the connection open although the useful page is already loaded.
        log(f"Navigation timeout ignored: {exc}")

    await page.wait_for_timeout(wait_ms)


async def close_modal(page) -> None:
    for pattern in [
        r"Verstanden und schließen",
        r"Verstanden",
        r"Schließen",
    ]:
        locator = page.get_by_text(re.compile(pattern, re.IGNORECASE))

        for i in range(await locator.count()):
            element = locator.nth(i)
            try:
                if not await element.is_visible():
