import os
from pathlib import Path

from playwright.sync_api import sync_playwright


base = os.environ.get("H3_TEST_URL", "http://127.0.0.1:8787")
output = Path(__file__).parent / os.environ.get("H3_SCREENSHOT", "mobile-smoke.png")
desktop_output = output.with_name(f"{output.stem}-desktop{output.suffix}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    errors = []

    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(base, wait_until="networkidle")

    assert page.locator("h1").inner_text() == "H3 Studio"
    assert page.locator("html").get_attribute("dir") == "rtl"
    assert page.get_by_text("הגדרות יצירה", exact=True).is_visible()
    newest_job = page.locator(".job-card").first
    assert newest_job.locator(".job-config").is_visible()
    assert newest_job.locator(".job-config span").count() >= 4

    engines = page.locator(".engine-toggle button")
    encoders = page.locator(".encoder-toggle button")
    assert engines.nth(0).get_attribute("aria-pressed") == "true"
    assert encoders.nth(0).get_attribute("aria-pressed") == "true"
    assert encoders.count() == 2
    assert page.locator(".steps-range").input_value() == "4"
    assert page.locator(".resolution-grid button.active").inner_text().startswith("מאוזן")

    turbo_profiles = page.locator(".turbo-profile-toggle button")
    assert turbo_profiles.count() == 2
    assert turbo_profiles.nth(0).get_attribute("aria-pressed") == "true"
    assert not turbo_profiles.nth(1).is_disabled()
    turbo_profiles.nth(1).click()
    assert page.locator(".steps-range").get_attribute("max") == "8"

    engines.nth(1).click()
    step_range = page.locator(".steps-range")
    assert step_range.input_value() == "20"
    assert step_range.get_attribute("min") == "8"
    assert step_range.get_attribute("max") == "30"

    page.locator(".resolution-grid button").nth(2).click()
    assert "864×480" in page.locator(".resolution-grid button.active").inner_text()

    page.locator(".mode-card", has_text="רפרנס").click()
    assert engines.nth(0).is_disabled()
    assert engines.nth(1).get_attribute("aria-pressed") == "true"
    assert page.get_by_text("רפרנס עובד עם רגיל או Spectrum; Turbo לא מתאים למסלול הזה", exact=True).is_visible()
    assert page.locator(".reference-grid .dropzone").count() == 2
    assert page.get_by_text("הוסף אודיו לרפרנס", exact=True).is_visible()

    page.locator(".mode-card", has_text="טקסט בלבד").click()
    page.locator(".batch-toggle input").check()
    assert page.locator(".sequence-choice button").count() == 2
    page.locator(".sequence-choice button", has_text="רצף מחובר").click()
    assert page.get_by_text("האפליקציה תייצר לפי הסדר, תבדוק כל שוט, תחלץ את הפריים האחרון ותחבר MP4 סופי אחד.", exact=True).is_visible()
    page.locator(".batch-toggle input").uncheck()
    engines.nth(0).click()
    page.locator(".turbo-profile-toggle button").nth(0).click()
    step_range.fill("12")
    page.get_by_role("button", name="10 שנ׳").click()
    page.locator("textarea").fill("A quiet cinematic forest with soft rain and clear natural audio")
    page.get_by_role("button", name="צור וידאו").click()
    dialog = page.get_by_role("dialog")
    assert dialog.is_visible()
    assert dialog.get_by_text("ההגדרה הזו כבדה", exact=True).is_visible()
    dialog.get_by_role("button", name="חזרה להגדרות").click()

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(output), full_page=False)

    desktop = browser.new_page(viewport={"width": 720, "height": 900}, device_scale_factor=1)
    desktop.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    desktop.goto(base, wait_until="networkidle")
    assert desktop.get_by_text("הגדרות יצירה", exact=True).is_visible()
    assert desktop.locator(".settings-grid").evaluate("element => getComputedStyle(element).gridTemplateColumns.split(' ').length === 2")
    assert desktop.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    desktop.screenshot(path=str(desktop_output), full_page=False)

    assert not errors, errors
    print({
        "title": page.title(),
        "dir": page.locator("html").get_attribute("dir"),
        "mobile": str(output),
        "desktop": str(desktop_output),
        "console_errors": errors,
    })
    browser.close()
