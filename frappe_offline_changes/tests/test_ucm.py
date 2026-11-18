"""The app on Unified Case Management records, with nothing changed in that app.

The settings name the field that holds a record's Context and the field that names the person a duplicate
was merged into; who reads and writes a person stays decided by Unified Case Management itself. These tests
check that the two fit: field officers of one delegation working offline on the same synthetic person, one
of another delegation, a right withdrawn and a person merged while a device was away.

They need the `ucm` app and skip without it, so this app's suite runs on Frappe alone.
"""

import unittest
import uuid

import frappe
from frappe.tests import IntegrationTestCase

from frappe_offline_changes import install
from frappe_offline_changes.api.changes import submit
from frappe_offline_changes.offline_changes import processing

try:
	from ucm.permissions import clear_cache, sharing
	from ucm.tests.utils import make_context, make_person, make_user
	from ucm.ucm import merge
except ImportError:
	clear_cache = None

REVIEWER = "Offline Change Reviewer"


@unittest.skipUnless(clear_cache, "Unified Case Management is not installed")
class TestOnUnifiedCaseManagement(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.a, cls.b = make_context("TOA"), make_context("TOB")
		cls.officer, cls.colleague = (
			make_user(f"offline.{n}.a@example.org", [(cls.a, "Write")]) for n in (1, 2)
		)
		cls.elsewhere = make_user("offline.1.b@example.org", [(cls.b, "Write")])
		cls.manager_a = make_user("offline.dm.a@example.org", [(cls.a, "Write")])
		cls.manager_b = make_user("offline.dm.b@example.org", [(cls.b, "Write")])
		for manager, context in ((cls.manager_a, cls.a), (cls.manager_b, cls.b)):
			frappe.get_doc("User", manager).add_roles(sharing.DATA_MANAGER, REVIEWER)
			# A Data Manager is a member of a Data Manager team of the delegation: the role alone is not enough
			frappe.db.set_value("Team", {"team_name": f"Contexts of {manager}"}, "team_is_data_manager", 1)
			frappe.get_doc(
				{
					"doctype": "Offline Review Scope",
					"user": manager,
					"scope_doctype": "Context",
					"scope_name": context,
				}
			).insert()

	@classmethod
	def tearDownClass(cls):
		clear_cache()
		super().tearDownClass()

	def setUp(self):
		self.act_as("Administrator")
		settings = frappe.get_single("Offline Change Settings")
		settings.enabled, settings.reviewers_see_unscoped = 1, 0
		settings.set(
			"doctypes",
			[
				{
					"reference_doctype": "Person",
					"allow_create": 1,
					"allow_update": 1,
					"scope_field": "context_tech_id",
					"replaced_by_field": "person_merged_tech_id",
				}
			],
		)
		settings.save()
		frappe.db.delete("Conflict Rule")
		install.add_rules()
		self.person = make_person(self.a, "Amina Test Diallo")
		self.addCleanup(self.act_as, "Administrator")

	def act_as(self, user):
		frappe.set_user(user)
		clear_cache()

	def read(self, name=None):
		"""The copy a device takes of the person while connected."""
		return frappe.get_doc("Person", name or self.person.name)

	def update(self, copy, **fields):
		return {
			"change_id": str(uuid.uuid4()),
			"operation": "Update",
			"doctype": "Person",
			"name": copy.name,
			"base_modified": str(copy.modified),
			"fields": {
				fieldname: {"from": copy.get(fieldname), "to": value} for fieldname, value in fields.items()
			},
		}

	def send(self, user, *changes):
		self.act_as(user)
		batch = submit(changes=list(changes), device_id=f"tablet of {user}")
		processing.process_batch(batch["batch_id"])
		self.act_as("Administrator")
		return [frappe.get_doc("Offline Change", {"change_id": change["change_id"]}) for change in changes]

	def now(self, fieldname, name=None):
		return frappe.db.get_value("Person", name or self.person.name, fieldname)

	def test_two_officers_change_different_fields_of_a_person(self):
		first = self.update(self.read(), person_mobile_phone="+41 22 555 01 01")
		second = self.update(self.read(), person_remark="Met at the registration point")
		(applied,) = self.send(self.officer, first)
		(merged,) = self.send(self.colleague, second)
		self.assertEqual((applied.status, applied.situation), ("Applied", "Unchanged"), applied.message)
		self.assertEqual(
			(merged.status, merged.situation), ("Applied", "Different fields changed"), merged.message
		)
		self.assertEqual(self.now("person_mobile_phone"), "+41 22 555 01 01")
		self.assertEqual(self.now("person_remark"), "Met at the registration point")
		# The change is filed under the person's delegation, read from the person
		self.assertEqual((merged.scope_doctype, merged.scope_name), ("Context", self.a))

	def test_two_officers_change_the_same_field(self):
		first = self.update(self.read(), person_mobile_phone="+41 22 555 01 01")
		second = self.update(self.read(), person_mobile_phone="+41 22 555 02 02")
		self.send(self.officer, first)
		(change,) = self.send(self.colleague, second)
		self.assertEqual((change.status, change.situation), ("Applied", "Same field changed"), change.message)
		self.assertEqual(self.now("person_mobile_phone"), "+41 22 555 02 02")
		self.assertEqual(
			(change.has_lost_values, change.field_changes[0].server_value), (1, "+41 22 555 01 01")
		)

	def test_a_name_in_conflict_waits_for_the_data_manager_of_the_delegation(self):
		frappe.get_doc(
			{
				"doctype": "Conflict Rule",
				"situation": "Same field changed",
				"outcome": "Hold for review",
				"reference_doctype": "Person",
				"fieldname": "person_name",
			}
		).insert()
		first = self.update(self.read(), person_name="Amina Test Dialo")
		second = self.update(
			self.read(), person_name="Aminata Test Diallo", person_remark="Name as on her card"
		)
		self.send(self.officer, first)
		(change,) = self.send(self.colleague, second)
		self.assertEqual(change.status, "Held", change.message)
		self.assertEqual((self.now("person_name"), self.now("person_remark")), ("Amina Test Dialo", None))

		# Seen by the Data Manager of the person's delegation, and by no other delegation's
		self.assertTrue(frappe.has_permission("Offline Change", "write", change, user=self.manager_a))
		self.assertFalse(frappe.has_permission("Offline Change", "read", change, user=self.manager_b))
		for manager, listed in ((self.manager_a, [change.name]), (self.manager_b, [])):
			self.act_as(manager)
			self.assertEqual(
				frappe.get_list("Offline Change", filters={"name": change.name}, pluck="name"), listed
			)

		self.act_as(self.manager_a)
		change = frappe.get_doc("Offline Change", change.name)
		next(row for row in change.field_changes if row.conflict).resolution = "Device"
		self.assertTrue(change.resolve())
		self.act_as("Administrator")
		self.assertEqual(
			(self.now("person_name"), self.now("person_remark")),
			("Aminata Test Diallo", "Name as on her card"),
		)

	def test_an_officer_of_another_delegation_changes_nothing(self):
		copy = self.read()
		(change,) = self.send(self.elsewhere, self.update(copy, person_remark="Seen from elsewhere"))
		self.assertEqual((change.status, change.situation), ("Refused", "No access"), change.message)
		self.assertIsNone(self.now("person_remark"))
		# Refused, and still filed under the person's own delegation: its Data Manager sees the attempt
		self.assertEqual(change.scope_name, self.a)
		self.assertTrue(frappe.has_permission("Offline Change", "read", change, user=self.manager_a))
		self.assertFalse(frappe.has_permission("Offline Change", "read", change, user=self.manager_b))

	def test_a_right_withdrawn_while_offline_is_withdrawn(self):
		device = self.update(self.read(), person_remark="Captured before the right was withdrawn")
		team = frappe.db.get_value("Team", {"team_name": f"Contexts of {self.officer}"})
		profile = frappe.db.get_value(
			"Team Security Profile", {"team_tech_id": team, "context_tech_id": self.a}
		)
		frappe.delete_doc("Team Security Profile", profile, force=True)
		clear_cache()
		try:
			(change,) = self.send(self.officer, device)
			self.assertEqual((change.status, change.situation), ("Refused", "No access"), change.message)
			self.assertIsNone(self.now("person_remark"))
			self.assertEqual(change.field_changes[0].device_value, "Captured before the right was withdrawn")
		finally:
			make_user(self.officer, [(self.a, "Write")])

	def test_a_change_follows_a_person_merged_while_offline(self):
		duplicate = make_person(self.a, "Amina Test Diallo")
		device = self.update(self.read(duplicate.name), person_remark="Captured on the duplicate")
		self.act_as(self.manager_a)
		merge.merge(self.person.name, duplicate.name)
		(change,) = self.send(self.officer, device)
		self.assertEqual(
			(change.status, change.situation, change.applied_to),
			("Applied", "Record replaced on server", self.person.name),
			change.message,
		)
		self.assertEqual(self.now("person_remark"), "Captured on the duplicate")
		self.assertIsNone(self.now("person_remark", duplicate.name))

	def test_a_person_registered_offline_keeps_the_name_the_device_gave(self):
		name = str(uuid.uuid7())
		create = {
			"change_id": str(uuid.uuid4()),
			"operation": "Create",
			"doctype": "Person",
			"name": name,
			"values": {"person_name": "Moussa Test Keita", "context_tech_id": self.a},
		}
		later = {
			"change_id": str(uuid.uuid4()),
			"operation": "Update",
			"doctype": "Person",
			"name": name,
			"fields": {"person_remark": {"from": None, "to": "Registered at the border point"}},
		}
		created, updated = self.send(self.officer, create, later)
		self.assertEqual(
			(created.status, created.applied_to, created.scope_name),
			("Applied", name, self.a),
			created.message,
		)
		self.assertEqual(updated.status, "Applied", updated.message)
		self.assertEqual(
			frappe.db.get_value("Person", name, ["person_name", "person_remark", "owner"]),
			("Moussa Test Keita", "Registered at the border point", self.officer),
		)
		# In a delegation the officer does not work in, the person is not registered
		elsewhere = {
			**create,
			"change_id": str(uuid.uuid4()),
			"name": str(uuid.uuid7()),
			"values": {**create["values"], "context_tech_id": self.b},
		}
		(refused,) = self.send(self.officer, elsewhere)
		self.assertIn(refused.status, ("Refused", "Failed"), refused.message)
		self.assertFalse(frappe.db.exists("Person", elsewhere["name"]))

	def test_a_delegation_holds_what_the_others_let_through(self):
		frappe.get_doc(
			{
				"doctype": "Conflict Rule",
				"situation": "Same field changed",
				"outcome": "Hold for review",
				"scope_doctype": "Context",
				"scope_name": self.b,
			}
		).insert()
		in_b = make_person(self.b, "Karim Test Haddad")
		for person, user in ((self.person, self.officer), (in_b, self.elsewhere)):
			device = self.update(self.read(person.name), person_mobile_phone="+41 22 555 03 03")
			frappe.get_doc("Person", person.name).update({"person_mobile_phone": "+41 22 555 04 04"}).save()
			(change,) = self.send(user, device)
			self.assertEqual(change.status, "Held" if person is in_b else "Applied", change.message)
