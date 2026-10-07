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


def log(message):
    print(f"[LBV] {message}", flush=True)


def today_berlin():
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def read_state():
    return STATE_FILE.read_text(encoding="utf-8").strip() if STATE_FILE.exists() else "NONE"


def write_state(value):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(value, encoding="utf-8")


def send_telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=30,
    )
    response.raise_for_status()


async def close_modal(page):
    for pattern in [
        r"Verstanden und schließen",
        r"Verstanden",
        r"Schließen",
    ]:
        locator = page.get_by_text(re.compile(pattern, re.IGNORECASE))
        for i in range(await locator.count()):
            element = locator.nth(i)
            try:
                if await element.is_visible():
                    try:
                        await element.click(force=True, timeout=2000)
                    except Exception:
                        await element.evaluate("(el) => el.click()")
                    await page.wait_for_timeout(400)
                    log("LBV information modal closed.")
                    return True
            except Exception:
                pass
    return False


async def close_cookie_banner(page):
    for pattern in [
        r"Alle akzeptieren",
        r"Akzeptieren",
        r"Einverstanden",
        r"Zustimmen",
    ]:
        locator = page.get_by_text(re.compile(pattern, re.IGNORECASE))
        for i in range(await locator.count()):
            element = locator.nth(i)
            try:
                if await element.is_visible():
                    try:
