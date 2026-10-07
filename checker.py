import asyncio
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


LBV_HOME = "https://lbv-termine.de/frontend/"
TARGET_DATE = date(2026, 12, 2)

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

STATE_FILE = Path(".state/last_alert.txt")


def log(message: str) -> None:
    print(f"[LBV] {message}", flush=True)


def get_berlin_today() -> date:
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def read_last_state() -> str:
    if STATE_FILE.exists():
        return STATE_FILE.read_text(encoding="utf-8").strip()
    return "NONE"


def write_state(value: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(value, encoding="utf-8")


def send_telegram(message: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()


async def dismiss_cookie_banner(page) -> None:
    patterns = [
        r"Alle akzeptieren",
        r"Akzeptieren",
        r"Einverstanden",
        r"Zustimmen",
    ]
async def close_lbv_welcome_modal(page) -> None:
    try:
        button = page.get_by_role(
            "button",
            name=re.compile(
                r"Verstanden und schließen",
                re.IGNORECASE,
            ),
        )

        if await button.count() > 0:
            if await button.first.is_visible():
                await button.first.click()
                await page.wait_for_timeout(500)
                log("LBV welcome modal closed.")
                return

    except Exception as exc:
        log(f"Welcome modal was not found or could not be closed: {exc}")
    for pattern in patterns:
        try:
            locator = page.get_by_role(
                "button", name=re.compile(pattern, re.IGNORECASE)
            )
            if await locator.count() > 0 and await locator.first.is_visible():
                await locator.first.click()
                await page.wait_for_timeout(300)
                return
        except Exception:
            pass


async def click_exact_text(page, text: str, timeout: int = 10000) -> None:
    locator = page.get_by_text(text, exact=True)
    await locator.first.wait_for(timeout=timeout)
    await locator.first.click()


async def click_service_flow(page) -> None:
    # Category
    try:
        await click_exact_text(page, "Führerschein")
    except Exception:
        locator = page.get_by_text(
            re.compile(r"^Führerschein(e)?$", re.IGNORECASE)
        )
        await locator.first.click()

    await page.wait_for_load_state("domcontentloaded")

    # Service
    await click_exact_text(
        page,
        "Abholung bestellter EU-Kartenführerschein",
    )

    await page.wait_for_load_state("domcontentloaded")


async def accept_privacy_if_present(page) -> None:
    # Tick the first visible checkbox, if the privacy page has one.
    checkboxes = page.locator('input[type="checkbox"]:visible')

    if await checkboxes.count() > 0:
        try:
            if not await checkboxes.first.is_checked():
                await checkboxes.first.check()
        except Exception:
            pass

    # Continue from the privacy page, if present.
    for pattern in [
        r"weiter",
        r"bestätigen",
        r"zustimmen",
        r"akzeptieren",
    ]:
        try:
            button = page.get_by_role(
                "button",
                name=re.compile(pattern, re.IGNORECASE),
            )

            visible_buttons = []
            for i in range(await button.count()):
                b = button.nth(i)
                if await b.is_visible():
                    visible_buttons.append(b)

            if visible_buttons:
                await visible_buttons[-1].click()
                await page.wait_for_timeout(500)
                return
        except Exception:
            pass


async def fill_personal_data(page) -> None:
    # Make sure "Private person" and "Ich" are selected.
    try:
        radio = page.get_by_text(
            "Der Termin ist für mich als Privatperson",
            exact=False,
        )
        if await radio.count() > 0:
            await radio.first.click()
    except Exception:
        pass

    try:
        ich = page.get_by_text("Ich", exact=True)
        if await ich.count() > 0:
            await ich.first.click()
    except Exception:
        pass

    first_name = os.environ["LBV_FIRST_NAME"]
    last_name = os.environ["LBV_LAST_NAME"]
    email = os.environ["LBV_EMAIL"]

    textboxes = page.get_by_role("textbox")
    visible_boxes = []

    for i in range(await textboxes.count()):
        box = textboxes.nth(i)
        if await box.is_visible():
            visible_boxes.append(box)

    if len(visible_boxes) < 3:
        raise RuntimeError(
            f"Could not find the 3 personal-data fields. Found {len(visible_boxes)}."
        )

    await visible_boxes[0].fill(first_name)
    await visible_boxes[1].fill(last_name)
    await visible_boxes[2].fill(email)

    # Continue to location selection.
    button = page.get_by_role(
        "button",
        name=re.compile(r"weiter zur Standortauswahl", re.IGNORECASE),
    )

    if await button.count() == 0:
        button = page.get_by_text(
            re.compile(r"weiter zur Standortauswahl", re.IGNORECASE)
        )

    await button.last.click()
    await page.wait_for_timeout(700)


async def select_location(page) -> None:
    await click_exact_text(page, "LBV Mitte Führerschein")

    await page.wait_for_timeout(300)

    button = page.get_by_role(
        "button",
        name=re.compile(r"auswählen", re.IGNORECASE),
    )

    if await button.count() == 0:
        button = page.get_by_text(
            re.compile(r"auswählen", re.IGNORECASE)
        )

    await button.last.click()
    await page.wait_for_timeout(700)


async def get_calendar_month(page):
    body = await page.locator("body").inner_text()

    pattern = (
        r"\b("
        + "|".join(map(re.escape, MONTHS.keys()))
        + r")\s+(\d{4})\b"
    )

    match = re.search(pattern, body)

    if not match:
        raise RuntimeError("Could not determine the calendar month.")

    month_name = match.group(1)
    year = int(match.group(2))

    return year, MONTHS[month_name]


async def click_month_arrow(page, direction: str) -> None:
    if direction not in {"<", ">"}:
        raise ValueError("direction must be '<' or '>'")

    # First try buttons and links with literal arrow text.
    for selector in ["button", "a"]:
        locator = page.locator(selector)

        for i in range(await locator.count()):
            element = locator.nth(i)

            try:
                if not await element.is_visible():
                    continue

                text = (await element.inner_text()).strip()
                aria = (
                    await element.get_attribute("aria-label") or ""
                ).strip().lower()

                if text == direction:
                    await element.click()
                    await page.wait_for_timeout(400)
                    return

                if direction == ">" and any(
                    x in aria
                    for x in [
                        "next",
                        "nächster",
                        "naechster",
                        "weiter",
                    ]
                ):
                    await element.click()
                    await page.wait_for_timeout(400)
                    return

                if direction == "<" and any(
                    x in aria
                    for x in [
                        "previous",
                        "prev",
                        "zurück",
                        "zurueck",
                    ]
                ):
                    await element.click()
                    await page.wait_for_timeout(400)
                    return

            except Exception:
                continue

    raise RuntimeError(f"Could not find calendar {direction} arrow.")


async def move_to_month(page, target_year: int, target_month: int) -> None:
    for _ in range(24):
        current_year, current_month = await get_calendar_month(page)

        current_index = current_year * 12 + current_month
        target_index = target_year * 12 + target_month

        if current_index == target_index:
            return

        if current_index < target_index:
            await click_month_arrow(page, ">")
        else:
            await click_month_arrow(page, "<")

    raise RuntimeError("Could not navigate to the required calendar month.")


async def get_clickable_days(page):
    cells = page.locator('td, [role="gridcell"]')
    days = []

    for i in range(await cells.count()):
        cell = cells.nth(i)

        try:
            if not await cell.is_visible():
                continue

            text = (await cell.inner_text()).strip()

            if not re.fullmatch(r"\d{1,2}", text):
                continue

            classes = (
                await cell.get_attribute("class") or ""
            ).lower()

            if any(
                word in classes
                for word in [
                    "other-month",
                    "othermonth",
                    "disabled",
                    "inactive",
                    "unavailable",
                ]
            ):
                continue

            aria_disabled = (
                await cell.get_attribute("aria-disabled") or ""
            ).lower()

            if aria_disabled == "true":
                continue

            interactive = cell.locator("a, button, [onclick]")

            if await interactive.count() == 0:
                continue

            days.append(int(text))

        except Exception:
            continue

    return sorted(set(days))


async def get_available_times(page):
    results = []

    for selector in ["button", "a"]:
        locator = page.locator(selector)

        for i in range(await locator.count()):
            element = locator.nth(i)

            try:
                if not await element.is_visible():
                    continue

                text = (await element.inner_text()).strip()

                if re.fullmatch(r"\d{2}:\d{2}", text):
                    if text not in results:
                        results.append(text)

            except Exception:
                continue

    return sorted(results)


async def click_calendar_day(page, day_number: int) -> bool:
    cells = page.locator('td, [role="gridcell"]')

    candidates = []

    for i in range(await cells.count()):
        cell = cells.nth(i)

        try:
            if not await cell.is_visible():
                continue

            text = (await cell.inner_text()).strip()

            if text != str(day_number):
                continue

            classes = (
                await cell.get_attribute("class") or ""
            ).lower()

            if any(
                word in classes
                for word in [
                    "other-month",
                    "othermonth",
                    "disabled",
                    "inactive",
                    "unavailable",
                ]
            ):
                continue

            aria_disabled = (
                await cell.get_attribute("aria-disabled") or ""
            ).lower()

            if aria_disabled == "true":
                continue

            candidates.append(cell)

        except Exception:
            continue

    if not candidates:
        return False

    cell = candidates[0]

    try:
        await cell.click()
        await page.wait_for_timeout(400)
        return True
    except Exception:
        try:
            child = cell.locator("a, button, [onclick]").first
            await child.click()
            await page.wait_for_timeout(400)
            return True
        except Exception:
            return False


async def find_earliest_appointment(page):
    today = get_berlin_today()

    current_year, current_month = await get_calendar_month(page)

    # Start at the current real-world month.
    await move_to_month(
        page,
        today.year,
        today.month,
    )

    scan_months = []

    year = today.year
    month = today.month

    while (year, month) <= (TARGET_DATE.year, TARGET_DATE.month):
        scan_months.append((year, month))

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    earliest = None

    for year, month in scan_months:
        await move_to_month(page, year, month)

        days = await get_clickable_days(page)

        log(f"Checking {month:02d}/{year}: days={days}")

        for day_number in days:
            try:
                candidate = date(year, month, day_number)
            except ValueError:
                continue

            if candidate < today:
                continue

            if candidate >= TARGET_DATE:
                continue

            clicked = await click_calendar_day(page, day_number)

            if not clicked:
                continue

            times = await get_available_times(page)

            if not times:
                continue

            if earliest is None or candidate < earliest["date"]:
                earliest = {
                    "date": candidate,
                    "times": times,
                }

        # Stop as soon as we reach the target month and have scanned it.
        if year == TARGET_DATE.year and month == TARGET_DATE.month:
            break

    return earliest


async def run_checker():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = await browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            ignore_https_errors=True,
            viewport={"width": 1440, "height": 1000},
        )

        page = await context.new_page()

        try:
            log("Opening LBV...")
            await page.goto(
    LBV_HOME,
    wait_until="domcontentloaded",
    timeout=60000,
)

await dismiss_cookie_banner(page)
await close_lbv_welcome_modal(page)

log("Selecting service...")
            )

            await dismiss_cookie_banner(page)

            log("Selecting service...")
            await click_service_flow(page)

            await accept_privacy_if_present(page)

            log("Entering personal data...")
            await fill_personal_data(page)

            log("Selecting LBV Mitte Führerschein...")
            await select_location(page)

            log("Searching calendar...")
            result = await find_earliest_appointment(page)

            return result

        finally:
            await browser.close()


def main():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    previous_state = read_last_state()

    try:
        result = asyncio.run(run_checker())

    except Exception as exc:
        log(f"ERROR: {exc}")
        raise

    if result is None:
        log("No appointment before 02.12.2026.")
        write_state("NONE")
        return

    appointment_date = result["date"]
    times = result["times"]

    fingerprint = (
        appointment_date.isoformat()
        + "|"
        + ",".join(times)
    )

    log(
        f"Appointment found: "
        f"{appointment_date.strftime('%d.%m.%Y')} "
        f"{', '.join(times)}"
    )

    if fingerprint == previous_state:
        log("Already notified about this exact availability.")
        return

    message = (
        "🚨 LBV APPOINTMENT AVAILABLE!\n\n"
        f"Date: {appointment_date.strftime('%d.%m.%Y')}\n"
        f"Times: {', '.join(times)}\n\n"
        "Book it manually here:\n"
        "https://lbv-termine.de/frontend/\n\n"
        "The checker does NOT book the appointment automatically."
    )

    send_telegram(message)

    write_state(fingerprint)

    log("Telegram notification sent.")


if __name__ == "__main__":
    main()
