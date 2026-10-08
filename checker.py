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

        if year == TARGET_DATE.year and month == TARGET_DATE.month:
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
        log("No appointment before 05.11.2026.")
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
