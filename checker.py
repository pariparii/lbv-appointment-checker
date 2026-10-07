

async def scan_calendar(page):
    today = today_berlin()
    year, month = today.year, today.month

    while True:
        await move_to_month(page, year, month)
        days = await get_available_days(page)
        log(f"Checking {month:02d}/{year}: {days}")

        for day_number in days:
            try:
                appointment_date = date(year, month, day_number)
            except ValueError:
                continue

            if appointment_date < today or appointment_date >= TARGET_DATE:
                continue

            if not await click_day(page, day_number):
                continue

            times = await get_available_times(page)
            if times:
                return {"date": appointment_date, "times": times}

        if year == TARGET_DATE.year and month == TARGET_DATE.month:
            break

        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1

    return None


async def run_checker():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
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
            await select_location(page)

            log("Scanning appointment calendar...")
            return await scan_calendar(page)
        finally:
            await browser.close()


async def accept_privacy_if_needed(page):
    body = ""
    try:
        body = await page.locator("body").inner_text()
    except Exception:
        pass

    if "Datenschutzerklärung" not in body:
        return

    log("Privacy page detected.")

    for i in range(await page.locator('input[type="checkbox"]:visible').count()):
        try:
            checkbox = page.locator('input[type="checkbox"]:visible').nth(i)
            if not await checkbox.is_checked():
                await checkbox.check(force=True)
        except Exception:
            pass

    for pattern in [r"weiter", r"bestätigen", r"zustimmen", r"akzeptieren"]:
        try:
            locator = page.get_by_text(re.compile(pattern, re.IGNORECASE))
            for i in range(await locator.count()):
                element = locator.nth(i)
                if await element.is_visible():
                    try:
                        await element.click(force=True)
                    except Exception:
                        await element.evaluate("(el) => el.click()")
                    await page.wait_for_timeout(700)
                    return
        except Exception:
            pass


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

    fingerprint = appointment_date.isoformat() + "|" + ",".join(times)

    if fingerprint == previous_state:
        log("Already notified about this exact availability.")
        return

    message = (
        "🚨 LBV APPOINTMENT AVAILABLE!\n\n"
        f"Date: {appointment_date.strftime('%d.%m.%Y')}\n"
        f"Times: {', '.join(times)}\n\n"
        "Open LBV and book manually:\n"
        f"{BASE_URL}\n\n"
        "The checker only checks availability. It does NOT book the appointment."
    )

    send_telegram(message)
    write_state(fingerprint)
    log("Telegram notification sent.")


if __name__ == "__main__":
    main()
