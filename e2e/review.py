"""A reviewer at the review screen, in a browser: resolve a held change, reject another, close a third.

Run by e2e/run.sh, which prepares the site, passes what this needs on standard input and removes it after.
"""

import json
import pathlib
import sys

from playwright.sync_api import expect, sync_playwright

SHOTS = pathlib.Path(__file__).parent / "screenshots"


def main():
	site = json.load(sys.stdin)
	SHOTS.mkdir(exist_ok=True)
	with sync_playwright() as playwright:
		# A bench tells its sites apart by the host name: the browser is told where that name lives, since a
		# development site's name is often known to no resolver
		address, port = site["url"].removeprefix("http://").split(":")
		browser = playwright.chromium.launch(args=[f"--host-resolver-rules=MAP {site['site']} {address}"])
		context = browser.new_context(
			base_url=f"http://{site['site']}:{port}",
			viewport={"width": 1400, "height": 1000},
		)
		context.add_cookies([{"name": "sid", "value": site["session"], "domain": site["site"], "path": "/"}])
		page = context.new_page()
		errors = []
		page.on("pageerror", lambda error: errors.append(str(error)))

		try:
			queue(page)
			resolve(page, site["changes"]["resolve"])
			reject(page, site["changes"]["reject"])
			close(page, site["changes"]["close"])
		except Exception:
			page.screenshot(path=SHOTS / "failure.png")
			raise
		finally:
			browser.close()
	if errors:
		sys.exit(f"The page raised errors: {errors[:3]}")
	print("The reviewer resolved, rejected and closed a change in the browser")


def open_change(page, name):
	page.goto(f"/desk/offline-change/{name}", wait_until="networkidle")
	expect(page.locator('.frappe-control[data-fieldname="field_changes"]').first).to_be_visible()


def queue(page):
	"""The reviewer finds the app and the changes that wait."""
	page.goto("/desk/offline-changes", wait_until="networkidle")
	expect(page.get_by_text("Changes captured offline")).to_be_visible()
	page.goto("/desk/offline-change?status=Held", wait_until="networkidle")
	expect(page.locator(".list-row-container .list-row")).to_have_count(2)
	page.screenshot(path=SHOTS / "1-queue.png")


def resolve(page, name):
	open_change(page, name)
	expect(page.get_by_text("For each field in conflict, choose the value the record keeps")).to_be_visible()
	page.screenshot(path=SHOTS / "2-held.png")
	# The field in conflict: open its row and take the device's value
	row = page.locator('[data-fieldname="field_changes"] .grid-row', has_text="Priority").first
	row.locator(".btn-open-row").click()
	form = page.locator(".grid-row-open")
	form.locator('select[data-fieldname="resolution"]').select_option("Device")
	page.screenshot(path=SHOTS / "3-choice.png")
	page.keyboard.press("Escape")
	page.get_by_role("button", name="Resolve", exact=True).click()
	page.get_by_role("button", name="Yes", exact=True).click()
	expect(page.locator(".page-head").get_by_text("Resolved", exact=True).first).to_be_visible()
	page.screenshot(path=SHOTS / "4-resolved.png")


def reject(page, name):
	open_change(page, name)
	page.get_by_role("button", name="Reject", exact=True).first.click()
	dialog = page.locator(".modal.show")
	dialog.locator('textarea[data-fieldname="reason"]').fill("Entered twice by the same officer")
	dialog.get_by_role("button", name="Reject", exact=True).click()
	expect(page.locator(".page-head").get_by_text("Rejected", exact=True).first).to_be_visible()
	page.screenshot(path=SHOTS / "5-rejected.png")


def close(page, name):
	open_change(page, name)
	expect(page.get_by_text("This change was applied over another value")).to_be_visible()
	page.get_by_role("button", name="Close", exact=True).first.click()
	expect(page.get_by_text("This change was applied over another value")).to_be_hidden()
	page.screenshot(path=SHOTS / "6-closed.png")


if __name__ == "__main__":
	main()
