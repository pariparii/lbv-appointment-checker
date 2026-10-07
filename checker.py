import asyncio
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.async_api import async_playwright


BASE_URL = "https://lbv-termine.de/frontend/"

FUEHRERSCHEIN_URL = (
    BASE_URL
    + "dienstleistungsauswahl.php?kategorieid=1"
)

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
    return datetime.now(
        ZoneInfo("Europe/Berlin")
    ).date()


def read_state():
    if STATE_FILE.exists():
        return STATE_FILE.read_text(
            encoding="utf-8"
        ).strip()

    return "NONE"


def write_state(value):
    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    STATE_FILE.write_text(
        value,
        encoding="utf-8"
    )


def send_telegram(message):

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

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


async def close_modal(page):

    patterns = [
        "Verstanden und schließen",
        "Verstanden",
        "Schließen",
    ]

    for pattern in patterns:

        locator = page.get_by_text(
            re.compile(
                pattern,
                re.IGNORECASE
            )
        )

        for i in range(
            await locator.count()
        ):

            element = locator.nth(i)

            try:

                if not await element.is_visible():
                    continue

                try:
                    await element.click(
                        force=True,
                        timeout=2000
                    )
                except Exception:
                    await element.evaluate(
                        "(el) => el.click()"
                    )

                await page.wait_for_timeout(
                    500
                )

                log(
                    "LBV information modal closed."
                )

                return True

            except Exception:
                pass

    return False


async def close_cookie_banner(page):

    patterns = [
        "Alle akzeptieren",
        "Akzeptieren",
        "Einverstanden",
        "Zustimmen",
    ]

    for pattern in patterns:

        locator = page.get_by_text(
            re.compile(
                pattern,
                re.IGNORECASE
            )
        )

        for i in range(
            await locator.count()
        ):

            element = locator.nth(i)

            try:

                if not await element.is_visible():
                    continue

                try:
                    await element.click(
                        force=True,
                        timeout=2000
                    )
                except Exception:
                    await element.evaluate(
                        "(el) => el.click()"
                    )

                await page.wait_for_timeout(
                    300
                )

                return

            except Exception:
                pass


async def open_service(page):

    log("Opening LBV...")

    await page.goto(
        BASE_URL,
        wait_until="commit",
        timeout=30000
    )

    await page.wait_for_timeout(
        4000
    )

    await close_cookie_banner(page)
    await close_modal(page)

    log(
        "Opening Führerschein service list..."
    )

    await page.goto(
        FUEHRERSCHEIN_URL,
        wait_until="commit",
        timeout=30000
    )

    await page.wait_for_timeout(
        3000
    )

    await close_cookie_banner(page)
    await close_modal(page)

    log(
        "Selecting EU-Kartenführerschein..."
    )

    result = await page.evaluate(
        """
        () => {

            const box =
                document.querySelector(
                    "#termin176"
                );

            if (!box) {
                return "NO_BOX";
            }

            const button =
                box.querySelector(
                    "button.LBV-choosebutton"
                );

            if (!button) {
                return "NO_BUTTON";
            }

            button.click();

            return "CLICKED";
        }
        """
    )

    log(
        f"EU service button result: {result}"
    )

    if result != "CLICKED":
        raise RuntimeError(
            "Could not select EU-Kartenführerschein."
        )

    await page.wait_for_timeout(
        4000
    )

    await close_modal(page)

    log(
        f"Current LBV URL: {page.url}"
    )


async def continue_from_description(page):

    if (
        "dienstleistungsbeschreibung.php"
        not in page.url
    ):
        return

    log(
        "LBV service description page detected."
    )

    await close_modal(page)

    # Possible button/link texts used by LBV
    patterns = [
        r"zum Vor-Ort-Termin",
        r"Termin vereinbaren",
        r"Termin buchen",
        r"zum Termin",
        r"weiter zum Termin",
        r"weiter",
        r"fortfahren",
    ]

    for pattern in patterns:

        locator = page.get_by_text(
            re.compile(
                pattern,
                re.IGNORECASE
            )
        )

        count = await locator.count()

        for i in range(count):

            element = locator.nth(i)

            try:

                if not await element.is_visible():
                    continue

                log(
                    f"Trying description button: "
                    f"{pattern}"
                )

                await element.scroll_into_view_if_needed()

                try:

                    await element.click(
                        force=True,
                        timeout=3000
                    )

                except Exception:

                    await element.evaluate(
                        "(el) => el.click()"
                    )

                await page.wait_for_timeout(
                    1500
                )

                # Check whether the page changed.
                if (
                    page.url
                    != BASE_URL
                ):
                    log(
                        f"Description step completed. "
                        f"Current URL: {page.url}"
                    )
                    return

            except Exception:
                continue

    # If text search didn't work, inspect buttons.
    buttons = page.locator(
        "button, input[type='submit'], a"
    )

    for i in range(
        await buttons.count()
    ):

        element = buttons.nth(i)

        try:

            if not await element.is_visible():
                continue

            text = (
                await element.inner_text()
            ).strip()

            if text:
                log(
                    f"Description page button: "
                    f"{text[:100]}"
                )

        except Exception:
            pass

    raise RuntimeError(
        "Could not continue from the "
        "LBV service description page."
    )


async def accept_privacy(page):

    try:
        body = await page.locator(
            "body"
        ).inner_text()
    except Exception:
        body = ""

    if "Datenschutzerklärung" not in body:
        return

    log(
        "Privacy page detected."
    )

    checkboxes = page.locator(
        'input[type="checkbox"]:visible'
    )

    for i in range(
        await checkboxes.count()
    ):

        try:

            checkbox = checkboxes.nth(i)

            if not await checkbox.is_checked():

                await checkbox.check(
                    force=True
                )

        except Exception:
            pass

    for pattern in [
        "weiter",
        "bestätigen",
        "zustimmen",
        "akzeptieren",
    ]:

        try:

            locator = page.get_by_text(
                re.compile(
                    pattern,
                    re.IGNORECASE
                )
            )

            for i in range(
                await locator.count()
            ):

                element = locator.nth(i)

                if not await element.is_visible():
                    continue

                try:
                    await element.click(
                        force=True
                    )
                except Exception:
                    await element.evaluate(
                        "(el) => el.click()"
                    )

                await page.wait_for_timeout(
                    700
                )

                return

        except Exception:
            pass


async def click_text(
    page,
    pattern
):

    locator = page.get_by_text(
        re.compile(
            pattern,
            re.IGNORECASE
        )
    )

    count = await locator.count()

    if count == 0:
        raise RuntimeError(
            f'Could not find "{pattern}"'
        )

    for i in range(
        count - 1,
        -1,
        -1
    ):

        element = locator.nth(i)

        try:

            if not await element.is_visible():
                continue

            await element.scroll_into_view_if_needed()

            try:

                await element.click(
                    force=True,
                    timeout=3000
                )

            except Exception:

                await element.evaluate(
                    "(el) => el.click()"
                )

            await page.wait_for_timeout(
                700
            )

            return

        except Exception:
            continue

    raise RuntimeError(
        f'Could not click "{pattern}"'
    )


async def fill_personal_data(page):

    log(
        "Entering personal data..."
    )

    await close_modal(page)

    first_name = os.environ[
        "LBV_FIRST_NAME"
    ]

    last_name = os.environ[
        "LBV_LAST_NAME"
    ]

    email = os.environ[
        "LBV_EMAIL"
    ]

    try:

        locator = page.get_by_text(
            re.compile(
                "Der Termin ist für mich als Privatperson",
                re.IGNORECASE
            )
        )

        if await locator.count() > 0:
            await locator.first.click(
                force=True
            )

    except Exception:
        pass

    try:

        locator = page.get_by_text(
            re.compile(
                r"^Ich$",
                re.IGNORECASE
            )
        )

        if await locator.count() > 0:
            await locator.first.click(
                force=True
            )

    except Exception:
        pass

    fields = page.locator(
        "input[type='text'], "
        "input[type='email']"
    )

    visible_fields = []

    for i in range(
        await fields.count()
    ):

        field = fields.nth(i)

        try:

            if await field.is_visible():
                visible_fields.append(
                    field
                )

        except Exception:
            pass

    log(
        f"Found {len(visible_fields)} "
        f"personal-data fields."
    )

    if len(visible_fields) < 3:

        raise RuntimeError(
            "Could not find the three "
            "personal-data fields."
        )

    await visible_fields[0].fill(
        first_name
    )

    await visible_fields[1].fill(
        last_name
    )

    await visible_fields[2].fill(
        email
    )

    log(
        "Personal data entered."
    )

    await click_text(
        page,
        r"weiter zur Standortauswahl"
    )

    await page.wait_for_timeout(
        1200
    )


async def select_location(page):

    log(
        "Selecting LBV Mitte Führerschein..."
    )

    await close_modal(page)

    await click_text(
        page,
        r"LBV Mitte Führerschein"
    )

    await page.wait_for_timeout(
        500
    )

    await click_text(
        page,
        r"^auswählen$"
    )

    await page.wait_for_timeout(
        1200
    )


async def get_calendar_month(page):

    body = await page.locator(
        "body"
    ).inner_text()

    pattern = (
        r"\b("
        + "|".join(
            re.escape(x)
            for x in MONTHS.keys()
        )
        + r")\s+(\d{4})\b"
    )

    match = re.search(
        pattern,
        body,
        re.IGNORECASE
    )

    if not match:
        raise RuntimeError(
            "Could not determine calendar month."
        )

    month_name = match.group(1)

    month_name = (
        month_name[0].upper()
        + month_name[1:]
    )

    return (
        int(match.group(2)),
        MONTHS[month_name]
    )


async def click_month_arrow(
    page,
    direction
):

    elements = page.locator(
        "button, a"
    )

    for i in range(
        await elements.count()
    ):

        element = elements.nth(i)

        try:

            if not await element.is_visible():
                continue

            text = (
                await element.inner_text()
            ).strip()

            if text == direction:

                await element.click(
                    force=True
                )

                await page.wait_for_timeout(
                    500
                )

                return

        except Exception:
            pass

    for i in range(
        await elements.count()
    ):

        element = elements.nth(i)

        try:

            if not await element.is_visible():
                continue

            aria = (
                await element.get_attribute(
                    "aria-label"
                )
                or ""
            ).lower()

            if direction == ">":
                words = [
                    "next",
                    "weiter",
                    "nächster",
                    "naechster"
                ]
            else:
                words = [
                    "previous",
                    "prev",
                    "zurück",
                    "zurueck"
                ]

            if any(
                word in aria
                for word in words
            ):

                await element.click(
                    force=True
                )

                await page.wait_for_timeout(
                    500
                )

                return

        except Exception:
            pass

    raise RuntimeError(
        "Could not find calendar arrow."
    )


async def move_to_month(
    page,
    target_year,
    target_month
):

    for _ in range(24):

        current_year, current_month = (
            await get_calendar_month(page)
        )

        current = (
            current_year * 12
            + current_month
        )

        target = (
            target_year * 12
            + target_month
        )

        if current == target:
            return

        if current < target:

            await click_month_arrow(
                page,
                ">"
            )

        else:

            await click_month_arrow(
                page,
                "<"
            )


async def get_available_days(page):

    days = []

    cells = page.locator(
        "td, [role='gridcell']"
    )

    for i in range(
        await cells.count()
    ):

        cell = cells.nth(i)

        try:

            if not await cell.is_visible():
                continue

            text = (
                await cell.inner_text()
            ).strip()

            if not re.fullmatch(
                r"\d{1,2}",
                text
            ):
                continue

            classes = (
                await cell.get_attribute(
                    "class"
                )
                or ""
            ).lower()

            if any(
                x in classes
                for x in [
                    "disabled",
                    "inactive",
                    "unavailable",
                    "other-month",
                    "othermonth"
                ]
            ):
                continue

            aria_disabled = (
                await cell.get_attribute(
                    "aria-disabled"
                )
                or ""
            ).lower()

            if aria_disabled == "true":
                continue

            interactive = cell.locator(
                "a, button, [onclick]"
            )

            if await interactive.count() == 0:
                continue

            days.append(
                int(text)
            )

        except Exception:
            pass

    return sorted(set(days))


async def click_day(
    page,
    day_number
):

    cells = page.locator(
        "td, [role='gridcell']"
    )

    for i in range(
        await cells.count()
    ):

        cell = cells.nth(i)

        try:

            if not await cell.is_visible():
                continue

            if (
                (
                    await cell.inner_text()
                ).strip()
                != str(day_number)
            ):
                continue

            await cell.scroll_into_view_if_needed()

            try:

                await cell.click(
                    force=True,
                    timeout=3000
                )

            except Exception:

                await cell.locator(
                    "a, button, [onclick]"
                ).first.click(
                    force=True
                )

            await page.wait_for_timeout(
                500
            )

            return True

        except Exception:
            continue

    return False


async def get_times(page):

    times = []

    elements = page.locator(
        "button, a"
    )

    for i in range(
        await elements.count()
    ):

        element = elements.nth(i)

        try:

            if not await element.is_visible():
                continue

            text = (
                await element.inner_text()
            ).strip()

            if re.fullmatch(
                r"\d{2}:\d{2}",
                text
            ):

                if text not in times:
                    times.append(text)

        except Exception:
            pass

    return sorted(times)


async def scan_calendar(page):

    today = today_berlin()

    year = today.year
    month = today.month

    while True:

        await move_to_month(
            page,
            year,
            month
        )

        days = await get_available_days(
            page
        )

        log(
            f"Checking "
            f"{month:02d}/{year}: "
            f"{days}"
        )

        for day in days:

            try:

                appointment_date = date(
                    year,
                    month,
                    day
                )

            except ValueError:
                continue

            if appointment_date < today:
                continue

            if appointment_date >= TARGET_DATE:
                continue

            if not await click_day(
                page,
                day
            ):
                continue

            times = await get_times(
                page
            )

            if times:

                return {
                    "date": appointment_date,
                    "times": times
                }

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

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        context = await browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 "
                "Safari/537.36"
            ),
            viewport={
                "width": 1440,
                "height": 1000
            }
        )

        page = await context.new_page()

        try:

            await open_service(page)

            # IMPORTANT NEW STEP:
            # the service selection lands on
            # dienstleistungsbeschreibung.php first.
            await continue_from_description(page)

            await accept_privacy(page)

            await fill_personal_data(page)

            await select_location(page)

            log(
                "Scanning appointment calendar..."
            )

            return await scan_calendar(page)

        finally:

            await browser.close()


def main():

    previous_state = read_state()

    try:

        result = asyncio.run(
            run_checker()
        )

    except Exception as error:

        log(
            f"ERROR: "
            f"{type(error).__name__}: "
            f"{error}"
        )

        raise

    if result is None:

        log(
            "No appointment before "
            "02.12.2026."
        )

        write_state(
            "NONE"
        )

        return

    appointment_date = result["date"]
    times = result["times"]

    fingerprint = (
        appointment_date.isoformat()
        + "|"
        + ",".join(times)
    )

    if fingerprint == previous_state:

        log(
            "Already notified."
        )

        return

    message = (
        "🚨 LBV APPOINTMENT AVAILABLE!\n\n"
        f"Date: "
        f"{appointment_date.strftime('%d.%m.%Y')}\n"
        f"Times: {', '.join(times)}\n\n"
        "Open LBV and book manually:\n"
        f"{BASE_URL}\n\n"
        "The checker only checks availability. "
        "It does NOT book the appointment."
    )

    send_telegram(message)

    write_state(
        fingerprint
    )

    log(
        "Telegram notification sent."
    )


if __name__ == "__main__":
    main()
