"""Changes sent by devices over HTTP, through the site's web server and its background worker.

test_changes.py covers every situation by calling the code directly, inside a transaction it rolls back.
These tests cover what that cannot: the request as a device makes it, the sign-in, the background job and
the user it runs as. They need the site served and a worker running, and skip when it is not; what they
create is committed, so each test removes it.
"""

from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from frappe_offline_changes import install
from frappe_offline_changes.tests.device import Device

USERS = ("offline.one@example.org", "offline.two@example.org", "offline.reviewer@example.org")
MARK = "Offline round trip"


def site_url() -> str:
	return f"http://127.0.0.1:{frappe.conf.webserver_port or 8000}"


def served() -> bool:
	try:
		response = requests.get(
			f"{site_url()}/api/method/ping", headers={"Host": frappe.local.site}, timeout=5
		)
		return response.ok
	except requests.RequestException:
		return False


class TestOverHTTP(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not served():
			raise cls.skipTest(cls, f"The site is not served at {site_url()}")
		cls.addClassCleanup(cls.remove_everything)
		cls.settings_before = frappe.get_single("Offline Change Settings").as_dict()
		cls.rules_before = frappe.get_all("Conflict Rule", pluck="name")
		install.add_rules()
		settings = frappe.get_single("Offline Change Settings")
		settings.enabled, settings.reviewers_see_unscoped = 1, 1
		settings.set(
			"doctypes",
			[{"reference_doctype": "ToDo", "allow_create": 1, "allow_update": 1, "allow_delete": 1}],
		)
		settings.save()
		cls.keys = {email: cls.make_user(email) for email in USERS}
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit -- reviewed: the web server and the worker are other processes, and see only what is committed

	@classmethod
	def make_user(cls, email):
		"""A user of the test with an API key; the secret exists for this run only."""
		roles = [{"role": "Offline Change Reviewer"}] if "reviewer" in email else []
		# A development site's generated users count against Frappe's limit on users created per hour
		with patch.dict(frappe.conf, {"throttle_user_limit": 100_000}):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": email.split("@")[0],
					"send_welcome_email": 0,
					"roles": roles,
				}
			).insert()
		secret = frappe.generate_hash(length=32)
		user.api_key, user.api_secret = frappe.generate_hash(length=15), secret
		user.save()
		return user.api_key, secret

	@classmethod
	def remove_everything(cls):
		frappe.db.rollback()
		frappe.set_user("Administrator")
		for name in frappe.get_all("Offline Change", filters={"user": ("in", USERS)}, pluck="name"):
			frappe.delete_doc("Offline Change", name, force=True)
		for name in frappe.get_all("ToDo", filters={"description": ("like", f"%{MARK}%")}, pluck="name"):
			frappe.delete_doc("ToDo", name, force=True)
		for name in frappe.get_all(
			"Conflict Rule", filters={"name": ("not in", cls.rules_before)}, pluck="name"
		):
			frappe.delete_doc("Conflict Rule", name, force=True)
		for email in USERS:
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True)
		settings = frappe.get_single("Offline Change Settings")
		settings.enabled = cls.settings_before.enabled
		settings.reviewers_see_unscoped = cls.settings_before.reviewers_see_unscoped
		settings.set(
			"doctypes",
			[{k: v for k, v in row.items() if k != "name"} for row in cls.settings_before.doctypes],
		)
		settings.save()
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit -- reviewed: removes what the test committed

	def device(self, email, device_id):
		return Device(site_url(), *self.keys[email], device_id=device_id, site=frappe.local.site)

	def todo(self, **values):
		"""A record on the site that both field users may change, and the reviewer too."""
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": MARK,
				"owner": USERS[0],
				"allocated_to": USERS[1],
				"assigned_by": USERS[2],
				**values,
			}
		).insert()
		frappe.db.set_value("ToDo", todo.name, "owner", USERS[0])
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit -- reviewed: the devices read it over HTTP
		return todo.name

	def on_site(self, doctype, name, fieldname):
		frappe.db.rollback()  # a new read: the value another process committed
		return frappe.db.get_value(doctype, name, fieldname)

	def outcomes(self, device):
		outcomes = device.outcomes()
		if any(outcome["status"] == "Received" for outcome in outcomes.values()):
			self.skipTest("No background worker is processing the site's jobs")
		return outcomes

	def test_a_change_and_a_new_record_reach_the_site(self):
		name = self.todo()
		device = self.device(USERS[0], "tablet-1")
		todo = device.read("ToDo", name)
		changed = device.change(todo, priority="High")
		new = device.create("ToDo", description=f"{MARK}, made on the device")
		later = device.change(new, priority="Low")
		self.assertEqual(set(device.sync().values()), {"Received"})

		outcomes = self.outcomes(device)
		self.assertEqual({outcome["status"] for outcome in outcomes.values()}, {"Applied"}, outcomes)
		self.assertEqual(self.on_site("ToDo", name, "priority"), "High")
		# The record made on the device has the site's name now, and the change made to it afterwards followed
		created = outcomes[later]["name"]
		self.assertNotEqual(created, new["name"])
		self.assertEqual(frappe.db.get_value("ToDo", created, ["priority", "owner"]), ("Low", USERS[0]))

		# The connection was lost before the answer: the batch is sent again, and nothing is applied twice
		frappe.db.set_value("ToDo", name, "priority", "Medium")
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit -- reviewed: the server reads it
		self.assertEqual(device.send_again()[changed], "Applied")
		self.assertEqual(self.on_site("ToDo", name, "priority"), "Medium")
		self.assertEqual(
			frappe.db.count("ToDo", {"description": ("like", f"%{MARK}, made on the device%")}), 1
		)

	def test_a_record_changed_on_two_devices(self):
		"""The acceptance case of the offline requirement: both devices read, both change, both reconnect."""
		name = self.todo()
		first, second = self.device(USERS[0], "tablet-1"), self.device(USERS[1], "tablet-2")
		copies = [device.read("ToDo", name) for device in (first, second)]
		first.change(copies[0], priority="High")
		conflicting = second.change(copies[1], priority="Low", color="#0000ff")
		first.sync()
		self.assertEqual({o["status"] for o in self.outcomes(first).values()}, {"Applied"})
		second.sync()
		outcome = self.outcomes(second)[conflicting]

		# Detected: the second device started from a value the first had already replaced. Resolved by the rule
		self.assertEqual((outcome["status"], outcome["situation"]), ("Applied", "Same field changed"))
		self.assertEqual(self.on_site("ToDo", name, "priority"), "Low")
		kept = frappe.get_doc("Offline Change", {"change_id": conflicting})
		lost = next(row for row in kept.field_changes if row.fieldname == "priority")
		self.assertEqual(
			(kept.user, kept.has_lost_values, lost.conflict, lost.server_value), (USERS[1], 1, 1, "High")
		)

	def test_a_reviewer_resolves_a_held_change(self):
		rule = frappe.get_doc(
			{
				"doctype": "Conflict Rule",
				"situation": "Same field changed",
				"outcome": "Hold for review",
				"reference_doctype": "ToDo",
				"fieldname": "priority",
			}
		).insert()
		name = self.todo()
		self.addCleanup(frappe.delete_doc, "Conflict Rule", rule.name, force=True)
		first, second = self.device(USERS[0], "tablet-1"), self.device(USERS[1], "tablet-2")
		copies = [device.read("ToDo", name) for device in (first, second)]
		first.change(copies[0], priority="High")
		held = second.change(copies[1], priority="Low", color="#0000ff")
		first.sync()
		self.outcomes(first)
		second.sync()
		self.assertEqual(self.outcomes(second)[held]["status"], "Held")
		self.assertEqual(frappe.db.get_value("ToDo", name, ["priority", "color"]), ("High", None))

		# The reviewer does what the form does: reads the change, chooses a value per conflict, resolves
		reviewer = self.device(USERS[2], "desk")
		queued = reviewer.call(
			"frappe.client.get_list", doctype="Offline Change", filters={"change_id": held}
		)
		change = reviewer.read("Offline Change", queued[0]["name"])
		for row in change["field_changes"]:
			if row["conflict"]:
				row["resolution"] = "Device"
		self.assertTrue(reviewer.call("run_doc_method", docs=frappe.as_json(change), method="resolve"))
		self.assertEqual(self.on_site("ToDo", name, "priority"), "Low")
		self.assertEqual(frappe.db.get_value("ToDo", name, "color"), "#0000ff")
		self.assertEqual(
			frappe.db.get_value("Offline Change", change["name"], ["status", "resolved_by"]),
			("Resolved", USERS[2]),
		)
		self.assertEqual(second.outcomes()[held]["status"], "Resolved")

	def test_the_queue_is_closed_to_those_who_send(self):
		name = self.todo()
		first, second = self.device(USERS[0], "tablet-1"), self.device(USERS[1], "tablet-2")
		mine = first.change(first.read("ToDo", name), color="#00ff00")
		first.sync()
		self.outcomes(first)
		# A user reads neither the queue nor what became of another user's change, and cannot send it as theirs
		self.assertEqual(
			first.http.get(f"{site_url()}/api/resource/Offline Change", timeout=60).status_code, 403
		)
		self.assertEqual(second.call("frappe_offline_changes.api.changes.status", change_ids=[mine]), {})
		second.last_batch = first.last_batch
		self.assertRaises(requests.HTTPError, second.send_again)
		# and nobody calls without signing in
		anonymous = requests.post(
			f"{site_url()}/api/method/frappe_offline_changes.api.changes.submit",
			json={"changes": first.last_batch, "device_id": "nobody"},
			headers={"Host": frappe.local.site},
			timeout=60,
		)
		self.assertEqual(anonymous.status_code, 403)
