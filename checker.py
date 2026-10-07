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
DEBUG_DIR = Path("debug")


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


async def save_debug(page, name):
    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        await page.screenshot(
            path=str(
                DEBUG_DIR / f"{name}.png"
            ),
            full_page=True
        )
        log(
            f"Debug screenshot saved: "
            f"debug/{name}.png"
        )
    except Exception as e:
        log(
            f"Could not save screenshot: {e}"
        )

    try:
        html = await page.content()

        (DEBUG_DIR / f"{name}.html").write_text(
            html,
            encoding="utf-8"
        )

        log(
            f"Debug HTML saved: "
            f"debug/{name}.html"
        )
    except Exception as e:
        log(
            f"Could not save HTML: {e}"
        )


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

        for i in range(
            await locator.count()
        ):

            element = locator.nth(i)

            try:

                if not await element.is_visible():
                    continue

                await element.evaluate(
                    "(el) => el.click()"
                )

                await page.wait_for_timeout(
                    600
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

                await element.evaluate(
                    "(el) => el.click()"
                )

                await page.wait_for_timeout(
                    400
                )

                return

            except Exception:
                pass


async def click_fuehrerschein(page):

    log(
        "Selecting Führerschein..."
    )

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

                clicked = await element.evaluate(
                    """
                    (el) => {
                        let node = el;

                        for (
                            let i = 0;
                            i < 10 && node;
                            i++
                        ) {

                            if (
                                node.tagName === "BUTTON" ||
                                node.tagName === "A" ||
                                node.tagName === "LABEL" ||
                                node.hasAttribute("onclick") ||
                                node.getAttribute("role") === "button"
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

                if not clicked:
                    continue

            await page.wait_for_timeout(
                1500
            )

            await close_modal(page)

            return

        except Exception:
            continue

    raise RuntimeError(
        "Could not click Führerschein."
    )


async def click_eu_service(page):

    service_text = (
        "Abholung bestellter "
        "EU-Kartenführerschein"
    )

    log(
        "Looking for EU-Kartenführerschein..."
    )

    # Give the LBV page time to finish changing
    await page.wait_for_timeout(2000)

    await close_modal(page)

    await close_cookie_banner(page)

    locator = page.get_by_text(
        service_text,
        exact=False
    )

    count = await locator.count()

    log(
        f"Found {count} matching "
        f"EU-service elements."
    )

    if count == 0:
        await save_debug(
            page,
            "eu_service_not_found"
        )

        raise RuntimeError(
            "Could not find the EU-Kartenführerschein service."
        )

    for i in range(count):

        element = locator.nth(i)

        try:

            if not await element.is_visible():
                continue

            log(
                f"Trying EU-service element #{i + 1}..."
            )

            await element.scroll_into_view_if_needed()

            # 1. Normal click
            try:

                await element.click(
                    timeout=3000
                )

                await page.wait_for_timeout(
                    1200
                )

                log(
                    "EU-Kartenführerschein selected."
                )

                return

            except Exception as error:

                log(
                    "Normal click failed: "
                    f"{type(error).__name__}"
                )

            # 2. Look for radio / checkbox inside
            controls = element.locator(
                "input, button, a"
            )

            for j in range(
                await controls.count()
            ):

                control = controls.nth(j)

                try:

                    if not await control.is_visible():
                        continue

                    await control.click(
                        force=True,
                        timeout=2000
                    )

                    await page.wait_for_timeout(
                        1000
                    )

                    log(
                        "EU-service control clicked."
                    )

                    return

                except Exception:
                    pass

            # 3. Search parents for clickable elements
            clicked = await element.evaluate(
                """
                (el) => {

                    let node = el;

                    for (
                        let i = 0;
                        i < 12 && node;
                        i++
                    ) {

                        const radio =
                            node.querySelector(
                                'input[type="radio"]'
                            );

                        if (radio) {
                            radio.click();
                            return "radio";
                        }

                        const button =
                            node.querySelector(
                                'button'
                            );

                        if (button) {
                            button.click();
                            return "button";
                        }

                        const link =
                            node.querySelector(
                                'a'
                            );

                        if (link) {
                            link.click();
                            return "link";
                        }

                        if (
                            node.tagName === "BUTTON" ||
                            node.tagName === "A" ||
                            node.tagName === "LABEL" ||
                            node.hasAttribute("onclick") ||
                            node.getAttribute("role") === "button"
                        ) {
                            node.click();
                            return "parent";
                        }

                        node = node.parentElement;
                    }

                    return false;
                }
                """
            )

            if clicked:

                await page.wait_for_timeout(
                    1200
                )

                log(
                    f"EU-service selected via {clicked}."
                )

                return

            # 4. Mouse click at the element
            box = await element.bounding_box()

            if box:

                await page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2
                )

                await page.wait_for_timeout(
                    1200
                )

                log(
                    "EU-service clicked by coordinates."
                )

                return

        except Exception:
            continue

    # Nothing worked: save diagnostics.
    await save_debug(
        page,
        "eu_service_click_failed"
    )

    # Print useful information about the elements.
    for i in range(count):

        try:

            element = locator.nth(i)

            html = await element.evaluate(
                "(el) => el.outerHTML"
            )

            log(
                f"EU element #{i + 1} HTML:"
            )
            print(
                html,
                flush=True
            )

        except Exception:
            pass

    raise RuntimeError(
        "EU-Kartenführerschein was found "
        "but could not be clicked."
    )


async def select_service(page):

    await close_modal(page)

    await click_fuehrerschein(
        page
    )

    await click_eu_service(
        page
    )


async def accept_privacy(page):

    try:

        body = await page.locator(
            "body"
        ).inner_text()

    except Exception:

        body = ""

    if (
        "Datenschutzerklärung"
        not in body
    ):
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

                if await element.is_visible():

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


async def fill_personal_data(page):

    log(
        "Entering personal data..."
    )

    first_name = os.environ[
        "LBV_FIRST_NAME"
    ]

    last_name = os.environ[
        "LBV_LAST_NAME"
    ]

    email = os.environ[
        "LBV_EMAIL"
    ]

    fields = page.locator(
        "input[type='text'], "
        "input[type='email']"
    )

    visible = []

    for i in range(
        await fields.count()
    ):

        field = fields.nth(i)

        try:

            if await field.is_visible():
                visible.append(
                    field
                )

        except Exception:
            pass

    if len(visible) < 3:

        raise RuntimeError(
            "Could not find the personal-data fields."
        )

    await visible[0].fill(
        first_name
    )

    await visible[1].fill(
        last_name
    )

    await visible[2].fill(
        email
    )

    try:

        await click_text(
            page,
            r"weiter zur Standortauswahl"
        )

    except Exception:

        await save_debug(
            page,
            "personal_data_failed"
        )

        raise

    await page.wait_for_timeout(
        1000
    )


async def click_text(page, pattern):

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
                    timeout=3000
                )

            except Exception:

                await element.evaluate(
                    "(el) => el.click()"
                )

            await page.wait_for_timeout(
                600
            )

            return

        except Exception:
            continue

    raise RuntimeError(
        f'Could not click "{pattern}"'
    )


async def select_location(page):

    log(
        "Selecting LBV Mitte Führerschein..."
    )

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
        1000
    )


async def get_calendar_month(page):

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

            if (
                text == direction
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
        "Calendar arrow not found."
    )


async def move_to_month(
    page,
    target_year,
    target_month
):

    for _ in range(24):

        current_year, current_month = (
            await get_calendar_month(
                page
            )
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

            days.append(
                int(text)
            )

        except Exception:
            pass

    return sorted(
        set(days)
    )


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

            await cell.click(
                force=True
            )

            await page.wait_for_timeout(
                500
            )

            return True

        except Exception:
            pass

    return False


async def get_available_times(page):

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
                    times.append(
                        text
                    )

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

            appointment_date = date(
                year,
                month,
                day
            )

            if appointment_date < today:
                continue

            if appointment_date >= TARGET_DATE:
                continue

            if not await click_day(
                page,
                day
            ):
                continue

            times = await get_available_times(
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

            log("Opening LBV...")

            await page.goto(
                LBV_HOME,
                wait_until="commit",
                timeout=30000
            )

            await page.wait_for_timeout(
                5000
            )

            log(
                f"LBV URL: {page.url}"
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

            await accept_privacy(
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
        "The checker only checks availability. "
        "It does NOT book the appointment."
    )

    send_telegram(
        message
    )

    write_state(
        fingerprint
    )

    log(
        "Telegram notification sent."
    )


if __name__ == "__main__":
    main()
