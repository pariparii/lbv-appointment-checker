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


def telegram(message):
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


async def close_modal(page):

    patterns = [
        "Verstanden und schließen",
        "Verstanden",
        "Schließen",
        "schließen",
    ]

    for pattern in patterns:

        locator = page.get_by_text(
            re.compile(
                pattern,
                re.IGNORECASE
            )
        )

        for i in range(await locator.count()):

            element = locator.nth(i)

            try:
                if not await element.is_visible():
                    continue

                await element.evaluate(
                    "(el) => el.click()"
                )

                await page.wait_for_timeout(500)

                log("LBV information modal closed.")

                return True

            except Exception:
                pass

    return False


async def close_cookie_banner(page):

    for pattern in [
        "Alle akzeptieren",
        "Akzeptieren",
        "Einverstanden",
        "Zustimmen",
    ]:

        locator = page.get_by_text(
            re.compile(
                pattern,
                re.IGNORECASE
            )
        )

        for i in range(await locator.count()):

            element = locator.nth(i)

            try:
                if not await element.is_visible():
                    continue

                await element.evaluate(
                    "(el) => el.click()"
                )

                await page.wait_for_timeout(300)

                return

            except Exception:
                pass


async def click_service(page):

    text = "Abholung bestellter EU-Kartenführerschein"

    log("Selecting EU-Kartenführerschein...")

    locator = page.get_by_text(
        text,
        exact=False
    )

    count = await locator.count()

    if count == 0:
        raise RuntimeError(
            f'Could not find "{text}"'
        )

    # Try every visible occurrence.
    for i in range(count):

        element = locator.nth(i)

        try:

            if not await element.is_visible():
                continue

            await element.scroll_into_view_if_needed()

            # First try normal click.
            try:
                await element.click(
                    timeout=3000
                )

                await page.wait_for_timeout(800)

                log(
                    "EU-Kartenführerschein selected."
                )

                return

            except Exception:
                pass

            # If the text itself isn't clickable,
            # find a clickable parent.
            result = await element.evaluate(
                """
                (el) => {
                    let node = el;

                    for (let i = 0; i < 8 && node; i++) {

                        if (
                            node.tagName === 'BUTTON' ||
                            node.tagName === 'A' ||
                            node.tagName === 'LABEL' ||
                            node.hasAttribute('onclick') ||
                            node.getAttribute('role') === 'button'
                        ) {
                            node.click();
                            return true;
                        }

                        const radio =
                            node.querySelector(
                                'input[type="radio"]'
                            );

                        if (radio) {
                            radio.click();
                            return true;
                        }

                        node = node.parentElement;
                    }

                    return false;
                }
                """
            )

            if result:

                await page.wait_for_timeout(800)

                log(
                    "EU-Kartenführerschein selected."
                )

                return

        except Exception:
            continue

    # Final fallback: click the center of the text element.
    for i in range(count):

        element = locator.nth(i)

        try:

            if not await element.is_visible():
                continue

            box = await element.bounding_box()

            if box:

                await page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2
                )

                await page.wait_for_timeout(800)

                log(
                    "EU-Kartenführerschein selected."
                )

                return

        except Exception:
            continue

    raise RuntimeError(
        "The EU-Kartenführerschein service "
        "was found but could not be clicked."
    )


async def click_fuehrerschein(page):

    log("Selecting Führerschein...")

    locator = page.get_by_text(
        re.compile(
            r"^Führerschein$",
            re.IGNORECASE
        )
    )

    count = await locator.count()

    for i in range(count):

        element = locator.nth(i)

        try:

            if not await element.is_visible():
                continue

            await element.scroll_into_view_if_needed()

            try:
                await element.click(
                    timeout=3000
                )

            except Exception:

                result = await element.evaluate(
                    """
                    (el) => {
                        let node = el;

                        for (
                            let i = 0;
                            i < 8 && node;
                            i++
                        ) {

                            if (
                                node.tagName === 'BUTTON' ||
                                node.tagName === 'A' ||
                                node.tagName === 'LABEL' ||
                                node.hasAttribute('onclick') ||
                                node.getAttribute('role') === 'button'
                            ) {
                                node.click();
                                return true;
                            }

                            node = node.parentElement;
                        }

                        return false;
                    }
                    """
                )

                if not result:
                    continue

            await page.wait_for_timeout(800)

            return

        except Exception:
            continue

    raise RuntimeError(
        "Could not click Führerschein."
    )


async def select_service(page):

    await close_modal(page)

    await click_fuehrerschein()

    await page.wait_for_timeout(1000)

    await close_modal(page)

    await click_service(page)

    await page.wait_for_timeout(1000)


async def fill_personal_data(page):

    log("Entering personal data...")

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

    # Private person
    try:

        locator = page.get_by_text(
            re.compile(
                "Der Termin ist für mich als Privatperson",
                re.IGNORECASE
            )
        )

        if await locator.count():

            await locator.first.click(
                force=True
            )

    except Exception:
        pass

    # I / Ich
    try:

        locator = page.get_by_text(
            re.compile(
                r"^Ich$",
                re.IGNORECASE
            )
        )

        if await locator.count():

            await locator.first.click(
                force=True
            )

    except Exception:
        pass

    fields = page.locator(
        "input[type='text'], input[type='email']"
    )

    visible = []

    for i in range(await fields.count()):

        field = fields.nth(i)

        try:

            if await field.is_visible():
                visible.append(field)

        except Exception:
            pass

    if len(visible) < 3:

        raise RuntimeError(
            "Could not find the three personal-data fields."
        )

    await visible[0].fill(first_name)
    await visible[1].fill(last_name)
    await visible[2].fill(email)

    log("Personal data entered.")

    await click_text(
        page,
        r"weiter zur Standortauswahl"
    )

    await page.wait_for_timeout(1000)


async def click_text(page, pattern):

    locator = page.get_by_text(
        re.compile(
            pattern,
            re.IGNORECASE
        )
    )

    count = await locator.count()

    for i in range(count - 1, -1, -1):

        element = locator.nth(i)

        try:

            if not await element.is_visible():
                continue

            await element.scroll_into_view_if_needed()

            try:

                await element.click(
                    timeout=3000
                )

            except Exception:

                await element.evaluate(
                    "(el) => el.click()"
                )

            await page.wait_for_timeout(600)

            return

        except Exception:
            continue

    raise RuntimeError(
        f'Could not click "{pattern}"'
    )


async def select_location(page):

    log("Selecting LBV Mitte Führerschein...")

    await close_modal(page)

    await click_text(
        page,
        r"LBV Mitte Führerschein"
    )

    await page.wait_for_timeout(300)

    await click_text(
        page,
        r"^auswählen$"
    )

    await page.wait_for_timeout(1000)


async def calendar_month(page):

    body = await page.locator(
        "body"
    ).inner_text()

    pattern = (
        r"\b("
        + "|".join(MONTHS.keys())
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

    year = int(
        match.group(2)
    )

    return (
        year,
        MONTHS[month_name]
    )


async def month_arrow(page, direction):

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

            aria = (
                await element.get_attribute(
                    "aria-label"
                )
                or ""
            ).lower()

            if (
                direction == ">"
                and text == ">"
            ):

                await element.click(
                    force=True
                )

                await page.wait_for_timeout(
                    400
                )

                return

            if (
                direction == "<"
                and text == "<"
            ):

                await element.click(
                    force=True
                )

                await page.wait_for_timeout(
                    400
                )

                return

            if (
                direction == ">"
                and any(
                    x in aria
                    for x in [
                        "next",
                        "weiter",
                        "nächster",
                        "naechster"
                    ]
                )
            ):

                await element.click(
                    force=True
                )

                await page.wait_for_timeout(
                    400
                )

                return

            if (
                direction == "<"
                and any(
                    x in aria
                    for x in [
                        "previous",
                        "prev",
                        "zurück",
                        "zurueck"
                    ]
                )
            ):

                await element.click(
                    force=True
                )

                await page.wait_for_timeout(
                    400
                )

                return

        except Exception:
            pass

    raise RuntimeError(
        f"Could not find calendar arrow {direction}"
    )


async def move_to_month(
    page,
    target_year,
    target_month
):

    for _ in range(24):

        current_year, current_month = (
            await calendar_month(page)
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
            await month_arrow(
                page,
                ">"
            )
        else:
            await month_arrow(
                page,
                "<"
            )

    raise RuntimeError(
        "Could not reach requested month."
    )


async def available_days(page):

    result = []

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

            disabled = (
                await cell.get_attribute(
                    "aria-disabled"
                )
                or ""
            ).lower()

            if disabled == "true":
                continue

            interactive = cell.locator(
                "a, button, [onclick]"
            )

            if await interactive.count() == 0:
                continue

            result.append(
                int(text)
            )

        except Exception:
            pass

    return sorted(set(result))


async def click_day(page, number):

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
                != str(number)
            ):
                continue

            await cell.click(
                force=True
            )

            await page.wait_for_timeout(
                400
            )

            return True

        except Exception:
            pass

    return False


async def available_times(page):

    result = []

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

                if text not in result:
                    result.append(text)

        except Exception:
            pass

    return sorted(result)


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

        days = await available_days(
            page
        )

        log(
            f"Checking {month:02d}/{year}: {days}"
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

            times = await available_times(
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
            viewport={
                "width": 1440,
                "height": 1000
            }
        )

        page = await context.new_page()

        try:

            log("Opening LBV...")

            await page.goto(
                LBV_HOME,
                wait_until="domcontentloaded",
                timeout=60000
            )

            await page.wait_for_timeout(
                1000
            )

            await close_cookie_banner(
                page
            )

            await close_modal(
                page
            )

            await select_service(
                page
            )

            await fill_personal_data(
                page
            )

            await select_location(
                page
            )

            log(
                "Scanning appointment calendar..."
            )

            return await scan_calendar(
                page
            )

        finally:

            await browser.close()


def main():

    previous = read_state()

    try:

        result = asyncio.run(
            run_checker()
        )

    except Exception as error:

        log(
            f"ERROR: "
            f"{type(error).__name__}: {error}"
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

    appointment_date = result[
        "date"
    ]

    times = result[
        "times"
    ]

    fingerprint = (
        appointment_date.isoformat()
        + "|"
        + ",".join(times)
    )

    if fingerprint == previous:

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
        f"{LBV_HOME}\n\n"
        "The checker only checks availability."
    )

    telegram(message)

    write_state(
        fingerprint
    )

    log(
        "Telegram notification sent."
    )


if __name__ == "__main__":
    main()
