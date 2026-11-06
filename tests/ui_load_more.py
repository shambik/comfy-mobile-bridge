"""UI regression check for issue #33: jobs shown with "Load 24 more" must stay shown through the 2 s refresh.

Runs against a live bridge with more than 32 jobs (it only reads; nothing is submitted):

    H3_TEST_URL=http://127.0.0.1:8787 python tests/ui_load_more.py

Every refresh is forced to reload the full list by answering the revision check with a new value each time.
"""
import os

from playwright.sync_api import sync_playwright

base = os.environ.get("H3_TEST_URL", "http://127.0.0.1:8787")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    refreshes = {"n": 0}

    def changing_revision(route):
        refreshes["n"] += 1
        route.fulfill(json={"revision": f"load-more-{refreshes['n']}"})

    page.route("**/api/jobs/revision", changing_revision)
    page.goto(base, wait_until="networkidle")
    more = page.locator(".history-load-more")
    assert more.count() == 1, "needs a bridge with more than 32 jobs"
    remaining = lambda: int(more.inner_text().split("·")[1].split()[0]) if more.count() else 0
    before = remaining()
    more.click()
    for _ in range(60):  # the page's CSP blocks string waits, so poll from here
        if remaining() != before:
            break
        page.wait_for_timeout(250)
    after_click = remaining()
    assert after_click < before, ("Load more showed nothing", before, after_click)
    page.wait_for_timeout(7000)
    assert refreshes["n"] >= 2, ("the page did not refresh", refreshes)
    assert remaining() == after_click, ("loaded jobs were hidden again", before, after_click, remaining())
    assert not errors, errors
    print({"before": before, "after_click": after_click, "after_refreshes": remaining(), "refreshes": refreshes["n"]})
    browser.close()
