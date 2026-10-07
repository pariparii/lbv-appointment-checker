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
APPOINTMENT_URL = BASE_URL + "terminauswahl.php?standortid=109"

# Alert only for appointments strictly before 02.12.2026.
TARGET_DATE = date(2026, 12, 3)

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
                    continue
                try:
                    await element.click(force=True, timeout=2000)
                except Exception:
                    await element.evaluate("(el) => el.click()")
                await page.wait_for_timeout(400)
                log("LBV information modal closed.")
                return
            except Exception:
                pass


async def close_cookie_banner(page) -> None:
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
                if not await element.is_visible():
                    continue
                try:
                    await element.click(force=True, timeout=2000)
                except Exception:
                    await element.evaluate("(el) => el.click()")
                await page.wait_for_timeout(300)
                return
            except Exception:
                pass


async def click_text(page, pattern: str, timeout: int = 5000) -> None:
    locator = page.get_by_text(re.compile(pattern, re.IGNORECASE))
    count = await locator.count()

    if count == 0:
        raise RuntimeError(f'Could not find "{pattern}"')

    for i in range(count - 1, -1, -1):
        element = locator.nth(i)
        try:
            if not await element.is_visible():
                continue
            await element.scroll_into_view_if_needed()
            try:
                await element.click(force=True, timeout=timeout)
            except Exception:
                await element.evaluate("(el) => el.click()")
            await page.wait_for_timeout(700)
            return
        except Exception:
            continue

    raise RuntimeError(f'Could not click "{pattern}"')


async def select_fuehrerschein_service(page) -> None:
    log("Opening Führerschein service list...")

    await goto_lbv(page, FUEHRERSCHEIN_URL, wait_ms=3000)
    await close_cookie_banner(page)
    await close_modal(page)

    log("Selecting Abholung bestellter EU-Kartenführerschein...")

    result = await page.evaluate(
        """
        () => {
            const box = document.querySelector("#termin176");
            if (!box) return "NO_BOX";

            const button = box.querySelector("button.LBV-choosebutton");
            if (!button) return "NO_BUTTON";

            button.click();
            return "CLICKED";
        }
        """
    )

    log(f"EU service button result: {result}")

    if result != "CLICKED":
        raise RuntimeError("Could not select EU-Kartenführerschein.")

    await page.wait_for_timeout(2500)
    await close_modal(page)
    log(f"After service selection: {page.url}")


async def continue_from_description(page) -> None:
    if "dienstleistungsbeschreibung.php" not in page.url:
        return

    log("LBV service description page detected.")

    pattern = r"weiter zur Terminvereinbarung"
    locator = page.get_by_role(
        "button",
        name=re.compile(pattern, re.IGNORECASE),
    )

    if await locator.count() == 0:
        locator = page.get_by_text(
            re.compile(pattern, re.IGNORECASE)
        )

    if await locator.count() == 0:
        raise RuntimeError(
            "Could not find 'weiter zur Terminvereinbarung'."
        )

    for i in range(await locator.count()):
        element = locator.nth(i)
        try:
            if not await element.is_visible():
                continue
            await element.scroll_into_view_if_needed()
            try:
                await element.click(force=True, timeout=5000)
            except Exception:
                await element.evaluate("(el) => el.click()")
            await page.wait_for_timeout(1500)
            log(f"After appointment step: {page.url}")
            return
        except Exception:
            pass

    raise RuntimeError(
        "Could not click 'weiter zur Terminvereinbarung'."
    )


async def accept_privacy_if_needed(page) -> None:
    try:
        body = await page.locator("body").inner_text()
    except Exception:
        body = ""

    if "Datenschutzerklärung" not in body:
        return

    log("Privacy page detected.")

    boxes = page.locator('input[type="checkbox"]:visible')
    for i in range(await boxes.count()):
        try:
            box = boxes.nth(i)
            if not await box.is_checked():
                await box.check(force=True)
        except Exception:
            pass

    for pattern in [r"weiter", r"bestätigen", r"zustimmen", r"akzeptieren"]:
        locator = page.get_by_text(re.compile(pattern, re.IGNORECASE))
        for i in range(await locator.count()):
            element = locator.nth(i)
            try:
                if not await element.is_visible():
                    continue
                try:
                    await element.click(force=True)
                except Exception:
                    await element.evaluate("(el) => el.click()")
                await page.wait_for_timeout(700)
                return
            except Exception:
                pass


async def fill_personal_data(page) -> None:
    log("Entering personal data...")
    await close_modal(page)

    first_name = os.environ["LBV_FIRST_NAME"]
    last_name = os.environ["LBV_LAST_NAME"]
    email = os.environ["LBV_EMAIL"]

    for pattern in [
        r"Der Termin ist für mich als Privatperson",
        r"^Ich$",
    ]:
        locator = page.get_by_text(re.compile(pattern, re.IGNORECASE))
        for i in range(await locator.count()):
            try:
                element = locator.nth(i)
                if await element.is_visible():
                    await element.click(force=True)
                    break
            except Exception:
                pass

    inputs = page.locator("input:visible")
    fields = []

    for i in range(await inputs.count()):
        field = inputs.nth(i)
        try:
            field_type = (await field.get_attribute("type") or "text").lower()
            if field_type not in {
                "hidden",
                "radio",
                "checkbox",
                "submit",
                "button",
            }:
                fields.append(field)
        except Exception:
            pass

    log(f"Found {len(fields)} visible personal-data fields.")

    if len(fields) < 3:
        raise RuntimeError(
            "Could not find the three personal-data fields."
        )

    await fields[0].fill(first_name)
    await fields[1].fill(last_name)
    await fields[2].fill(email)

    log("Personal data entered.")
    await click_text(page, r"weiter zur Standortauswahl")
    await page.wait_for_timeout(1000)


async def open_target_calendar(page) -> None:
    log("Opening LBV Mitte Führerschein calendar directly...")
    await goto_lbv(page, APPOINTMENT_URL, wait_ms=2500)
    await close_modal(page)
    log(f"Calendar URL: {page.url}")


async def get_calendar_month(page):
    body = await page.locator("body").inner_text()
    pattern = (
        r"\b("
        + "|".join(re.escape(name) for name in MONTHS)
        + r")\s+(\d{4})\b"
    )
    match = re.search(pattern, body, re.IGNORECASE)

    if not match:
        raise RuntimeError("Could not determine calendar month.")

    month_name = match.group(1)
    month_name = month_name[:1].upper() + month_name[1:]
    return int(match.group(2)), MONTHS[month_name]


async def click_month_arrow(page, direction: str) -> None:
    elements = page.locator("button, a")

    for i in range(await elements.count()):
        element = elements.nth(i)
        try:
            if not await element.is_visible():
                continue
            if (await element.inner_text()).strip() == direction:
                await element.click(force=True)
                await page.wait_for_timeout(500)
                return
        except Exception:
            pass

    if direction == ">":
        words = ["next", "weiter", "nächster", "naechster"]
    else:
        words = ["previous", "prev", "zurück", "zurueck"]

    for i in range(await elements.count()):
        element = elements.nth(i)
        try:
            if not await element.is_visible():
                continue
            aria = (await element.get_attribute("aria-label") or "").lower()
            if any(word in aria for word in words):
                await element.click(force=True)
                await page.wait_for_timeout(500)
                return
        except Exception:
            pass

    raise RuntimeError(f"Could not find calendar arrow {direction}.")


async def move_to_month(page, target_year: int, target_month: int) -> None:
    for _ in range(24):
        current_year, current_month = await get_calendar_month(page)
        current_index = current_year * 12 + current_month
        target_index = target_year * 12 + target_month

        if current_index == target_index:
            return

        await click_month_arrow(
            page,
            ">" if current_index < target_index else "<",
        )

    raise RuntimeError("Could not reach requested calendar month.")


def is_other_month_class(classes: str) -> bool:
    classes = classes.lower()
    return any(
        x in classes
        for x in [
            "other-month",
            "othermonth",
            "outside-month",
            "outside_month",
            "ui-datepicker-other-month",
        ]
    )


async def get_calendar_day_cells(page):
    """
    Be deliberately permissive. The previous version returned [] because
    it assumed too much about LBV's CSS classes and clickable children.
    We collect visible table cells containing exactly one/two digits and
    let click_day() test whether each one is actually selectable.
    """
    candidates = []

    cells = page.locator("td")

    for i in range(await cells.count()):
        cell = cells.nth(i)

        try:
            if not await cell.is_visible():
                continue

            text = (await cell.inner_text()).strip()

            if not re.fullmatch(r"\d{1,2}", text):
                continue

            classes = await cell.get_attribute("class") or ""

            if is_other_month_class(classes):
                continue

            candidates.append(cell)

        except Exception:
            pass

    return candidates


async def try_click_day_and_get_times(page, cell):
    """
    Try the cell itself, then common child controls. If the LBV calendar
    marks a date unavailable, these clicks should not produce appointment
    times; an available date will.
    """
    try:
        await cell.scroll_into_view_if_needed()
    except Exception:
        pass

    click_targets = [cell]

    for selector in [
        "a",
        "button",
        "input",
        "[onclick]",
        "[role='button']",
    ]:
        try:
            children = cell.locator(selector)
            for j in range(await children.count()):
                click_targets.append(children.nth(j))
        except Exception:
            pass

    for target in click_targets:
        try:
            if not await target.is_visible():
                continue

            try:
                await target.click(force=True, timeout=1500)
            except Exception:
                await target.evaluate("(el) => el.click()")

            await page.wait_for_timeout(350)

            times = await get_available_times(page)

            if times:
                return times

        except Exception:
            pass

    return []


async def get_available_times(page):
    times = []

    # First, look for visible elements with HH:MM text.
    elements = page.locator("button, a, input, span, div")

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
    today = today_berlin()

    year = today.year
    month = today.month

    while True:
        await move_to_month(page, year, month)

        cells = await get_calendar_day_cells(page)

        numeric_days = []
        for cell in cells:
            try:
                numeric_days.append(int((await cell.inner_text()).strip()))
            except Exception:
                pass

        log(
            f"Checking {month:02d}/{year}: "
            f"calendar contains day cells {sorted(set(numeric_days))}"
        )

        for cell in cells:
            try:
                day_number = int((await cell.inner_text()).strip())
                appointment_date = date(year, month, day_number)
            except Exception:
                continue

            if appointment_date < today:
                continue

            if appointment_date >= TARGET_DATE:
                continue

            times = await try_click_day_and_get_times(page, cell)

            if times:
                log(
                    f"AVAILABLE: "
                    f"{appointment_date.strftime('%d.%m.%Y')} "
                    f"{', '.join(times)}"
                )
                return {
                    "date": appointment_date,
                    "times": times,
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
            ],
        )

        context = await browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 1000},
        )

        page = await context.new_page()

        try:
            await select_fuehrerschein_service(page)
            await continue_from_description(page)
            await accept_privacy_if_needed(page)
            await fill_personal_data(page)

            await open_target_calendar(page)

            log("Scanning appointment calendar...")
            return await scan_calendar(page)

        finally:
            await browser.close()


def main():
    previous_state = read_state()

    try:
        result = asyncio.run(run_checker())
    except Exception as error:
        log(f"ERROR: {type(error).__name__}: {error}")
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

    if fingerprint == previous_state:
        log("Already notified about this exact availability.")
        return

    message = (
        "🚨 LBV APPOINTMENT AVAILABLE!\n\n"
        f"Date: {appointment_date.strftime('%d.%m.%Y')}\n"
        f"Times: {', '.join(times)}\n\n"
        "Open LBV and book manually:\n"
        f"{BASE_URL}\n\n"
        "The checker only checks availability. "
        "It does NOT book the appointment."
    )

    send_telegram(message)
    write_state(fingerprint)
    log("Telegram notification sent.")


if __name__ == "__main__":
    main()
