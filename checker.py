import asyncio
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.async_api import async_playwright


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


def log(message: str):
    print(f"[LBV] {message}", flush=True)


def get_today():
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def read_last_state():
    if STATE_FILE.exists():
        return STATE_FILE.read_text(encoding="utf-8").strip()
    return "NONE"


def write_state(value: str):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(value, encoding="utf-8")


def send_telegram(message: str):
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


async def close_any_modal(page):
    """
    Closes the LBV welcome/information modal if it appears.
    """
    patterns = [
        r"Verstanden und schließen",
        r"Verstanden",
        r"Schließen",
        r"schließen",
    ]

    for pattern in patterns:
        try:
            locator = page.get_by_text(
                re.compile(pattern, re.IGNORECASE)
            )

            for i in range(await locator.count()):
                element = locator.nth(i)

                if await element.is_visible():
                    try:
                        await element.click(force=True)
                    except Exception:
                        await element.evaluate(
                            "(el) => el.click()"
                        )

                    await page.wait_for_timeout(700)
                    log("LBV information modal closed.")
                    return True

        except Exception:
            pass

    return False


async def dismiss_cookie_banner(page):
    patterns = [
        r"Alle akzeptieren",
        r"Akzeptieren",
        r"Einverstanden",
        r"Zustimmen",
    ]

    for pattern in patterns:
        try:
            locator = page.get_by_text(
                re.compile(pattern, re.IGNORECASE)
            )

            for i in range(await locator.count()):
                element = locator.nth(i)

                if await element.is_visible():
                    try:
                        await element.click(force=True)
                    except Exception:
                        await element.evaluate(
                            "(el) => el.click()"
                        )

                    await page.wait_for_timeout(300)
                    return

        except Exception:
            pass


async def click_text(page, text_pattern: str, timeout=15000):
    locator = page.get_by_text(
        re.compile(text_pattern, re.IGNORECASE)
    )

    count = await locator.count()

    if count == 0:
        raise RuntimeError(
            f'Could not find text: "{text_pattern}"'
        )

    for i in range(count - 1, -1, -1):
        element = locator.nth(i)

        try:
            if await element.is_visible():
                await element.scroll_into_view_if_needed()

                try:
                    await element.click(timeout=3000)
                except Exception:
                    await element.click(
                        force=True,
                        timeout=3000
                    )

                await page.wait_for_timeout(700)
                return

        except Exception:
            continue

    raise RuntimeError(
        f'Found "{text_pattern}" but could not click it.'
    )


async def select_service(page):
    log("Selecting Führerschein...")

    await close_any_modal(page)

    try:
        await click_text(
            page,
            r"^Führerschein$",
        )
    except Exception:
        await click_text(
            page,
            r"Führerschein",
        )

    await page.wait_for_timeout(1000)

    await close_any_modal(page)

    log("Selecting EU-Kartenführerschein...")

    await click_text(
        page,
        r"Abholung bestellter EU-Kartenführerschein",
    )

    await page.wait_for_timeout(1000)


async def fill_person_data(page):
    log("Entering personal data...")

    await close_any_modal(page)

    # Private person
    try:
        await click_text(
            page,
            r"Der Termin ist für mich als Privatperson",
        )
    except Exception:
        pass

    # "Ich"
    try:
        await click_text(page, r"^Ich$")
    except Exception:
        pass

    first_name = os.environ["LBV_FIRST_NAME"]
    last_name = os.environ["LBV_LAST_NAME"]
    email = os.environ["LBV_EMAIL"]

    inputs = page.locator(
        'input[type="text"], input[type="email"]'
    )

    visible_inputs = []

    for i in range(await inputs.count()):
        element = inputs.nth(i)

        try:
            if await element.is_visible():
                visible_inputs.append(element)
        except Exception:
            pass

    if len(visible_inputs) < 3:
        raise RuntimeError(
            f"Could not find personal-data fields. "
            f"Found {len(visible_inputs)} fields."
        )

    await visible_inputs[0].fill(first_name)
    await visible_inputs[1].fill(last_name)
    await visible_inputs[2].fill(email)

    log("Personal data entered.")

    await click_text(
        page,
        r"weiter zur Standortauswahl",
    )

    await page.wait_for_timeout(1000)


async def select_location(page):
    log("Selecting LBV Mitte Führerschein...")

    await close_any_modal(page)

    await click_text(
        page,
        r"LBV Mitte Führerschein",
    )

    await page.wait_for_timeout(300)

    await click_text(
        page,
        r"^auswählen$",
    )

    await page.wait_for_timeout(1000)


async def get_calendar_month(page):
    body = await page.locator("body").inner_text()

    pattern = (
        r"\b("
        + "|".join(MONTHS.keys())
        + r")\s+(\d{4})\b"
    )

    match = re.search(
        pattern,
        body,
        re.IGNORECASE,
    )

    if not match:
        raise RuntimeError(
            "Could not determine calendar month."
        )

    month_name = match.group(1)

    # Restore proper capitalization for dictionary lookup
    month_name = month_name[:1].upper() + month_name[1:]

    year = int(match.group(2))

    return year, MONTHS[month_name]


async def click_month_arrow(page, direction):
    buttons = page.locator("button, a")

    for i in range(await buttons.count()):
        element = buttons.nth(i)

        try:
            if not await element.is_visible():
                continue

            text = (await element.inner_text()).strip()
            aria = (
                await element.get_attribute("aria-label") or ""
            ).lower()

            if direction == ">" and text == ">":
                await element.click(force=True)
                await page.wait_for_timeout(500)
                return

            if direction == "<" and text == "<":
                await element.click(force=True)
                await page.wait_for_timeout(500)
                return

            if direction == ">":
                if any(
                    word in aria
                    for word in [
                        "next",
                        "nächster",
                        "naechster",
                        "weiter",
                    ]
                ):
                    await element.click(force=True)
                    await page.wait_for_timeout(500)
                    return

            if direction == "<":
                if any(
                    word in aria
                    for word in [
                        "previous",
                        "prev",
                        "zurück",
                        "zurueck",
                    ]
                ):
                    await element.click(force=True)
                    await page.wait_for_timeout(500)
                    return

        except Exception:
            continue

    raise RuntimeError(
        f"Could not find calendar arrow {direction}."
    )


async def move_to_month(page, target_year, target_month):
    for _ in range(24):
        current_year, current_month = (
            await get_calendar_month(page)
        )

        current_index = current_year * 12 + current_month
        target_index = target_year * 12 + target_month

        if current_index == target_index:
            return

        if current_index < target_index:
            await click_month_arrow(page, ">")
        else:
            await click_month_arrow(page, "<")

    raise RuntimeError(
        "Could not navigate to requested month."
    )


async def get_available_days(page):
    days = []

    cells = page.locator(
        'td, [role="gridcell"]'
    )

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
                    "disabled",
                    "inactive",
                    "unavailable",
                    "other-month",
                    "othermonth",
                ]
            ):
                continue

            aria_disabled = (
                await cell.get_attribute(
                    "aria-disabled"
                ) or ""
            ).lower()

            if aria_disabled == "true":
                continue

            interactive = cell.locator(
                "a, button, [onclick]"
            )

            if await interactive.count() == 0:
                continue

            days.append(int(text))

        except Exception:
            pass

    return sorted(set(days))


async def click_day(page, day_number):
    cells = page.locator(
        'td, [role="gridcell"]'
    )

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
                    "disabled",
                    "inactive",
                    "unavailable",
                    "other-month",
                    "othermonth",
                ]
            ):
                continue

            aria_disabled = (
                await cell.get_attribute(
                    "aria-disabled"
                ) or ""
            ).lower()

            if aria_disabled == "true":
                continue

            try:
                await cell.click(force=True)
            except Exception:
                child = cell.locator(
                    "a, button, [onclick]"
                ).first

                await child.click(force=True)

            await page.wait_for_timeout(500)
            return True

        except Exception:
            continue

    return False


async def get_times(page):
    times = []

    elements = page.locator(
        "button, a"
    )

    for i in range(await elements.count()):
        element = elements.nth(i)

        try:
            if not await element.is_visible():
                continue

            text = (await element.inner_text()).strip()

            if re.fullmatch(r"\d{2}:\d{2}", text):
                if text not in times:
                    times.append(text)

        except Exception:
            pass

    return sorted(times)


async def scan_calendar(page):
    today = get_today()

    year = today.year
    month = today.month

    while True:

        await move_to_month(
            page,
            year,
            month,
        )

        days = await get_available_days(page)

        log(
            f"Checking calendar "
            f"{month:02d}/{year}: {days}"
        )

        for day_number in days:

            try:
                appointment_date = date(
                    year,
                    month,
                    day_number,
                )
            except ValueError:
                continue

            if appointment_date < today:
                continue

            if appointment_date >= TARGET_DATE:
                continue

            clicked = await click_day(
                page,
                day_number,
            )

            if not clicked:
                continue

            times = await get_times(page)

            if times:
                return {
                    "date": appointment_date,
                    "times": times,
                }

        # Stop once target month has been checked
        if (
            year == TARGET_DATE.year
            and month == TARGET_DATE.month
        ):
            break

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    return None


async def run_checker():

    async with async_playwright() as playwright:

        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = await browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={
                "width": 1440,
                "height": 1000,
            },
        )

        page = await context.new_page()

        try:

            log("Opening LBV...")

            await page.goto(
                LBV_HOME,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(1000)

            await dismiss_cookie_banner(page)

            await close_any_modal(page)

            await select_service(page)

            await fill_person_data(page)

            await select_location(page)

            log("Scanning appointment calendar...")

            result = await scan_calendar(page)

            return result

        finally:
            await browser.close()


def main():

    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    previous_state = read_last_state()

    try:
        result = asyncio.run(
            run_checker()
        )

    except Exception as error:

        log(
            f"ERROR: {type(error).__name__}: {error}"
        )

        raise

    if result is None:

        log(
            "No appointment before "
            "02.12.2026."
        )

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
        "Appointment found: "
        f"{appointment_date.strftime('%d.%m.%Y')} "
        f"{', '.join(times)}"
    )

    # Don't send the same notification every 5 minutes
    if fingerprint == previous_state:

        log(
            "Already notified about "
            "this availability."
        )

        return

    message = (
        "🚨 LBV APPOINTMENT AVAILABLE!\n\n"
        f"Date: "
        f"{appointment_date.strftime('%d.%m.%Y')}\n"
        f"Times: {', '.join(times)}\n\n"
        "Open LBV and book manually:\n"
        f"{LBV_HOME}\n\n"
        "The checker only checks availability. "
        "It does NOT book the appointment."
    )

    send_telegram(message)

    write_state(fingerprint)

    log(
        "Telegram notification sent."
    )


if __name__ == "__main__":
    main()
