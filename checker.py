async def open_service(page):

    log("Opening Führerschein service list directly...")

    try:
        await page.goto(
            FUEHRERSCHEIN_URL,
            wait_until="commit",
            timeout=30000
        )
    except Exception as error:
        # GitHub/LBV can sometimes keep the connection open
        # even though the page itself has already loaded.
        log(
            f"Initial navigation warning: "
            f"{type(error).__name__}: {error}"
        )

    await page.wait_for_timeout(5000)

    log(
        f"Current LBV URL: {page.url}"
    )

    await close_cookie_banner(page)
    await close_modal(page)

    # Make sure we actually reached the Führerschein page.
    if "dienstleistungsauswahl.php" not in page.url:
        raise RuntimeError(
            "LBV Führerschein service page "
            "was not reached."
        )

    log(
        "Selecting EU-Kartenführerschein..."
    )

    result = await page.evaluate(
        """
        () => {

            const box =
                document.querySelector("#termin176");

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

    await page.wait_for_timeout(3000)

    await close_modal(page)

    log(
        f"Current LBV URL after service selection: "
        f"{page.url}"
    )
