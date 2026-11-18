"""What the browser test of the review screen needs on the site, and its removal (e2e/run.sh).

The browser acts as a reviewer who finds three changes: two held on a conflict, one applied over another
value. Everything is synthetic, committed so that the web server sees it, and removed by `cleanup`. The
reviewer has no password: a session is opened for them here, as `bench browse` does, and handed to the caller.
"""

from unittest.mock import patch

import frappe
from frappe import _
from frappe.auth import CookieManager, LoginManager

from frappe_offline_changes import install
from frappe_offline_changes.api.changes import submit
from frappe_offline_changes.offline_changes import processing

REVIEWER = "offline.browser.reviewer@example.org"
MARK = "Offline review screen"
DEVICE = "browser-test"


def prepare() -> dict:
	"""Create the reviewer and the changes waiting for them; returns what the browser needs."""
	development_only()
	cleanup()
	install.add_rules()
	settings = frappe.get_single("Offline Change Settings")
	frappe.cache.set_value("offline_changes_e2e_settings", settings.as_json())
	settings.enabled, settings.reviewers_see_unscoped = 1, 1
	settings.set("doctypes", [{"reference_doctype": "ToDo", "allow_update": 1}])
	settings.save()
	frappe.get_doc(
		{
			"doctype": "Conflict Rule",
			"situation": "Same field changed",
			"outcome": "Hold for review",
			"reference_doctype": "ToDo",
			"fieldname": "priority",
			"description": MARK,
		}
	).insert()

	# A development site's generated users count against Frappe's limit on users created per hour
	with patch.dict(frappe.conf, {"throttle_user_limit": 100_000}):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": REVIEWER,
				"first_name": "Reviewer",
				"send_welcome_email": 0,
				"roles": [{"role": "Offline Change Reviewer"}],
			}
		).insert()

	changes = {
		"resolve": _conflict("priority", "High", "Low", color="#0000ff"),
		"reject": _conflict("priority", "High", "Low"),
		"close": _conflict("color", "#ff0000", "#00ff00"),
	}
	frappe.utils.set_request(path="/")
	frappe.local.cookie_manager = CookieManager()
	frappe.local.login_manager = LoginManager()
	frappe.local.login_manager.login_as(REVIEWER)
	session = frappe.session.sid
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit -- reviewed: the web server is another process, and sees only what is committed
	return {
		"url": f"http://127.0.0.1:{frappe.conf.webserver_port or 8000}",
		"site": frappe.local.site,
		"session": session,
		"changes": changes,
	}


def check():
	"""What the site holds after the browser has acted; raises unless it is what the reviewer chose.

	Read from the site and not from the page, which would show the same thing had nothing been saved."""
	found = set()
	for change in frappe.get_all(
		"Offline Change",
		filters={"device_id": DEVICE},
		fields=["status", "closed", "resolved_by", "reference_name"],
	):
		priority, color = frappe.db.get_value("ToDo", change.reference_name, ["priority", "color"])
		found.add((change.status, change.closed, change.resolved_by, priority, color))
	expected = {
		# resolved with the device's value for the field in conflict, the other field applied with it
		("Resolved", 0, REVIEWER, "Low", "#0000ff"),
		# rejected: the record keeps what the site held
		("Rejected", 0, REVIEWER, "High", None),
		# applied by the rule, then closed by the reviewer
		("Applied", 1, None, "Medium", "#00ff00"),
	}
	if found != expected:
		frappe.throw(_("The site does not hold what the reviewer chose: {0}").format(sorted(found, key=str)))


def cleanup():
	"""Remove what `prepare` created, and put the settings back."""
	development_only()
	for name in frappe.get_all("Offline Change", filters={"device_id": DEVICE}, pluck="name"):
		frappe.delete_doc("Offline Change", name, force=True)
	for name in frappe.get_all("ToDo", filters={"description": ("like", f"%{MARK}%")}, pluck="name"):
		frappe.delete_doc("ToDo", name, force=True)
	for name in frappe.get_all("Conflict Rule", filters={"description": MARK}, pluck="name"):
		frappe.delete_doc("Conflict Rule", name, force=True)
	if frappe.db.exists("User", REVIEWER):
		frappe.delete_doc("User", REVIEWER, force=True)
	before = frappe.cache.get_value("offline_changes_e2e_settings")
	if before:
		before = frappe.parse_json(before)
		settings = frappe.get_single("Offline Change Settings")
		settings.enabled, settings.reviewers_see_unscoped = before.enabled, before.reviewers_see_unscoped
		settings.set("doctypes", [{k: v for k, v in row.items() if k != "name"} for row in before.doctypes])
		settings.save()
		frappe.cache.delete_value("offline_changes_e2e_settings")
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit -- reviewed: removes what prepare committed


def development_only():
	if not frappe.conf.developer_mode:
		frappe.throw(_("The browser test creates a user and records: it runs on a development site only"))


def _conflict(fieldname, on_server, on_device, **also) -> str:
	"""A ToDo read by a device, changed on the site, then changed on the device; returns the queued change."""
	todo = frappe.get_doc({"doctype": "ToDo", "description": MARK, "assigned_by": REVIEWER}).insert()
	read = {"modified": str(todo.modified), **{f: todo.get(f) for f in (fieldname, *also)}}
	frappe.get_doc("ToDo", todo.name).update({fieldname: on_server}).save()
	change = {
		"change_id": frappe.generate_hash(length=20),
		"operation": "Update",
		"doctype": "ToDo",
		"name": todo.name,
		"base_modified": read["modified"],
		"fields": {f: {"from": read[f], "to": v} for f, v in {fieldname: on_device, **also}.items()},
	}
	batch = submit(changes=[change], device_id=DEVICE)
	processing.process_batch(batch["batch_id"])
	return frappe.db.get_value("Offline Change", {"change_id": change["change_id"]}, "name")
