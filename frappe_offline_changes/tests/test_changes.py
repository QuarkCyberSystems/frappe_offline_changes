"""Changes captured offline, from the device's call to the record: one test per situation.

The records changed are Frappe's own ToDo and Contact (for its table of e-mail addresses), so the suite runs
on Frappe alone. Two devices are two calls: each sends what it read and what it changed.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from frappe_offline_changes import install
from frappe_offline_changes.api.changes import status, submit
from frappe_offline_changes.offline_changes import processing
from frappe_offline_changes.offline_changes.doctype.conflict_rule.conflict_rule import find_rule
from frappe_offline_changes.offline_changes.doctype.offline_change.offline_change import (
	query_conditions,
	remove_old_values,
)

HERE = "frappe_offline_changes.tests.test_changes"
# What the app owning ToDo would answer: a ToDo belongs to its role, and a reviewer handles some roles
REPLACED = {}
REVIEWS = []
HOOKS = {
	"offline_changes": {"ToDo": {"scope": [f"{HERE}.scope"], "replaced_by": [f"{HERE}.replaced_by"]}},
	"offline_change_reviewer_scopes": [f"{HERE}.reviews"],
}


def scope(doctype, name, values):
	role = (values or {}).get("role") if not name else frappe.db.get_value(doctype, name, "role")
	return ("Role", role) if role else None


def replaced_by(doctype, name):
	return REPLACED.get(name)


def reviews(user):
	return list(REVIEWS)


class TestOfflineChanges(IntegrationTestCase):
	def setUp(self):
		settings = frappe.get_single("Offline Change Settings")
		settings.enabled, settings.max_batch_size, settings.keep_values_days = 1, 50, 30
		settings.set(
			"doctypes",
			[
				{"reference_doctype": doctype, "allow_create": 1, "allow_update": 1, "allow_delete": 1}
				for doctype in ("ToDo", "Contact")
			],
		)
		settings.save()
		frappe.db.delete("Conflict Rule")
		install.add_rules()
		REPLACED.clear()
		REVIEWS.clear()
		self.addCleanup(frappe.set_user, "Administrator")

	# What a device does

	def todo(self, **values):
		return frappe.get_doc({"doctype": "ToDo", "description": "Visit the family", **values}).insert()

	def user(self, email, role=None):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		)
		if role:
			user.append("roles", {"role": role})
		return user.insert()

	def update(self, doc, **fields):
		"""A change made on a device that read `doc`: each field as (the value read, the new value)."""
		return {
			"change_id": frappe.generate_hash(length=20),
			"operation": "Update",
			"doctype": doc.doctype,
			"name": doc.name,
			"base_modified": str(doc.modified),
			"fields": {fieldname: {"from": pair[0], "to": pair[1]} for fieldname, pair in fields.items()},
		}

	def send(self, *changes):
		"""Send a batch and run its job; returns the queue rows, in order."""
		batch = submit(changes=list(changes), device_id="tablet-1")
		processing.process_batch(batch["batch_id"])
		return [frappe.get_doc("Offline Change", {"change_id": change["change_id"]}) for change in changes]

	def rule(self, situation, outcome, **narrowed):
		return frappe.get_doc(
			{"doctype": "Conflict Rule", "situation": situation, "outcome": outcome, **narrowed}
		).insert()

	def value(self, doc, fieldname):
		return frappe.db.get_value(doc.doctype, doc.name, fieldname)

	# Updates

	def test_an_unchanged_record_takes_the_change(self):
		todo = self.todo()
		(change,) = self.send(self.update(todo, priority=("Medium", "High")))
		self.assertEqual((change.status, change.situation), ("Applied", "Unchanged"))
		self.assertEqual(change.field_changes[0].outcome, "Applied")
		self.assertEqual(self.value(todo, "priority"), "High")

	def test_different_fields_are_merged(self):
		todo = self.todo()
		device = self.update(todo, priority=("Medium", "High"))
		frappe.get_doc("ToDo", todo.name).update({"date": "2026-12-01"}).save()
		(change,) = self.send(device)
		self.assertEqual((change.status, change.situation), ("Applied", "Different fields changed"))
		self.assertEqual(self.value(todo, "priority"), "High")
		self.assertEqual(str(self.value(todo, "date")), "2026-12-01")

	def test_different_fields_are_held_when_the_rule_says_so(self):
		frappe.db.set_value(
			"Conflict Rule", {"situation": "Different fields changed"}, "outcome", "Hold for review"
		)
		todo = self.todo()
		device = self.update(todo, priority=("Medium", "High"))
		frappe.get_doc("ToDo", todo.name).update({"date": "2026-12-01"}).save()
		(change,) = self.send(device)
		self.assertEqual(change.status, "Held")
		self.assertEqual(self.value(todo, "priority"), "Medium")

	def test_the_same_field_goes_to_the_last_to_arrive(self):
		todo = self.todo()
		device = self.update(todo, priority=("Medium", "High"))
		frappe.get_doc("ToDo", todo.name).update({"priority": "Low"}).save()
		(change,) = self.send(device)
		self.assertEqual((change.status, change.situation), ("Applied", "Same field changed"))
		self.assertEqual(self.value(todo, "priority"), "High")
		# The value that lost is kept, with the rule that decided, until a reviewer closes the change
		row = change.field_changes[0]
		self.assertEqual((row.conflict, row.server_value, row.outcome), (1, "Low", "Applied"))
		self.assertTrue(change.has_lost_values and change.rule and row.rule)
		change.close()
		self.assertEqual(frappe.db.get_value("Offline Change", change.name, "closed"), 1)

	def test_the_server_value_stays_when_the_rule_says_so(self):
		frappe.db.set_value(
			"Conflict Rule", {"situation": "Same field changed"}, "outcome", "Server value stays"
		)
		todo = self.todo()
		device = self.update(todo, priority=("Medium", "High"), date=(str(todo.date), "2026-12-05"))
		frappe.get_doc("ToDo", todo.name).update({"priority": "Low"}).save()
		(change,) = self.send(device)
		self.assertEqual(change.status, "Applied")
		self.assertEqual(
			{row.fieldname: row.outcome for row in change.field_changes},
			{"priority": "Server kept", "date": "Applied"},
		)
		self.assertEqual(self.value(todo, "priority"), "Low")
		self.assertEqual(str(self.value(todo, "date")), "2026-12-05")

	def test_the_same_change_on_both_sides_is_no_conflict(self):
		todo = self.todo()
		device = self.update(todo, priority=("Medium", "High"))
		frappe.get_doc("ToDo", todo.name).update({"priority": "High"}).save()
		(change,) = self.send(device)
		self.assertEqual(
			(change.status, change.field_changes[0].conflict, change.field_changes[0].outcome),
			("Applied", 0, "Same"),
		)

	def test_a_field_held_for_review_holds_the_whole_change(self):
		self.rule("Same field changed", "Hold for review", reference_doctype="ToDo", fieldname="priority")
		todo = self.todo()
		device = self.update(todo, priority=("Medium", "High"), date=(str(todo.date), "2026-12-05"))
		frappe.get_doc("ToDo", todo.name).update({"priority": "Low"}).save()
		(change,) = self.send(device)
		self.assertEqual(change.status, "Held")
		self.assertEqual(self.value(todo, "priority"), "Low")
		self.assertEqual(str(self.value(todo, "date")), str(todo.date))
		return todo, change

	def test_a_reviewer_takes_the_device_value(self):
		todo, change = self.test_a_field_held_for_review_holds_the_whole_change()
		change.field_changes[0].resolution = "Device"
		self.assertTrue(change.resolve())
		self.assertEqual(self.value(todo, "priority"), "High")
		self.assertEqual(str(self.value(todo, "date")), "2026-12-05")
		change.reload()
		self.assertEqual((change.status, change.resolved_by), ("Resolved", "Administrator"))

	def test_a_reviewer_keeps_the_server_value_or_enters_another(self):
		todo, change = self.test_a_field_held_for_review_holds_the_whole_change()
		change.field_changes[0].resolution = "Server"
		change.field_changes[1].resolution, change.field_changes[1].resolved_value = "Other", "2026-12-24"
		self.assertTrue(change.resolve())
		self.assertEqual(self.value(todo, "priority"), "Low")
		self.assertEqual(str(self.value(todo, "date")), "2026-12-24")

	def test_a_conflict_without_a_choice_is_not_resolved(self):
		todo, change = self.test_a_field_held_for_review_holds_the_whole_change()
		self.assertFalse(change.resolve())
		self.assertEqual(frappe.db.get_value("Offline Change", change.name, "status"), "Held")
		self.assertEqual(self.value(todo, "priority"), "Low")

	def test_a_reviewer_rejects_a_change(self):
		_todo, change = self.test_a_field_held_for_review_holds_the_whole_change()
		self.assertRaises(frappe.ValidationError, change.reject, " ")
		change.reject("Entered twice")
		change.reload()
		self.assertEqual((change.status, change.message), ("Rejected", "Entered twice"))
		self.assertRaises(frappe.ValidationError, change.resolve)

	def test_what_was_sent_cannot_be_edited(self):
		_todo, change = self.test_a_field_held_for_review_holds_the_whole_change()
		change.field_changes[0].device_value = "Low"
		change.field_changes[0].resolution = "Device"
		change.payload = "{}"
		change.status = "Applied"
		change.save()
		change.reload()
		self.assertEqual((change.status, change.field_changes[0].device_value), ("Held", "High"))
		self.assertEqual(change.field_changes[0].resolution, "Device")
		self.assertIn("priority", change.payload)
		self.assertRaises(frappe.ValidationError, frappe.get_doc({"doctype": "Offline Change"}).insert)
		frappe.set_user("Guest")
		self.assertRaises(
			frappe.ValidationError, frappe.delete_doc, "Offline Change", change.name, ignore_permissions=True
		)

	def test_a_change_the_record_refuses_is_kept_as_failed(self):
		todo = self.todo()
		(change,) = self.send(self.update(todo, status=("Open", "Not a status")))
		self.assertEqual(change.status, "Failed")
		self.assertIn("Not a status", change.message)
		self.assertEqual(self.value(todo, "status"), "Open")

	# Records deleted or replaced

	def test_a_change_to_a_deleted_record_waits_for_a_reviewer(self):
		todo = self.todo()
		device = self.update(todo, priority=("Medium", "High"))
		frappe.delete_doc("ToDo", todo.name)
		(change,) = self.send(device)
		self.assertEqual((change.status, change.situation), ("Held", "Changed on device, deleted on server"))
		self.assertRaises(frappe.ValidationError, change.resolve)

	def test_the_deletion_stands_when_the_rule_says_so(self):
		frappe.db.set_value(
			"Conflict Rule",
			{"situation": "Changed on device, deleted on server"},
			"outcome",
			"Deletion stands",
		)
		todo = self.todo()
		device = self.update(todo, priority=("Medium", "High"))
		frappe.delete_doc("ToDo", todo.name)
		(change,) = self.send(device)
		self.assertEqual((change.status, change.has_lost_values), ("Rejected", 1))

	def test_a_change_follows_the_record_that_replaced_its_own(self):
		with self.patch_hooks(HOOKS):
			merged, kept = self.todo(), self.todo()
			REPLACED[merged.name] = kept.name
			(change,) = self.send(self.update(merged, priority=("Medium", "High")))
			self.assertEqual(
				(change.status, change.situation, change.applied_to),
				("Applied", "Record replaced on server", kept.name),
			)
			self.assertEqual(self.value(kept, "priority"), "High")
			self.assertEqual(self.value(merged, "priority"), "Medium")

			frappe.db.set_value(
				"Conflict Rule", {"situation": "Record replaced on server"}, "outcome", "Hold for review"
			)
			(change,) = self.send(self.update(merged, priority=("High", "Low")))
			self.assertEqual(change.status, "Held")
			self.assertTrue(change.resolve())
			self.assertEqual(self.value(kept, "priority"), "Low")

	def test_a_deletion_is_made_only_of_a_record_nobody_changed(self):
		todo = self.todo()
		delete = {
			"operation": "Delete",
			"doctype": "ToDo",
			"name": todo.name,
			"base_modified": str(todo.modified),
		}
		frappe.get_doc("ToDo", todo.name).update({"priority": "Low"}).save()
		(change,) = self.send({**delete, "change_id": "delete-1"})
		self.assertEqual((change.status, change.situation), ("Held", "Deleted on device, changed on server"))
		self.assertTrue(frappe.db.exists("ToDo", todo.name))
		self.assertTrue(change.resolve())
		self.assertFalse(frappe.db.exists("ToDo", todo.name))

		todo = self.todo()
		(change,) = self.send(
			{**delete, "change_id": "delete-2", "name": todo.name, "base_modified": str(todo.modified)}
		)
		self.assertEqual(change.status, "Applied")
		self.assertFalse(frappe.db.exists("ToDo", todo.name))

	# New records

	def test_a_record_created_offline_and_changed_before_it_was_sent(self):
		create = {
			"change_id": "create-1",
			"operation": "Create",
			"doctype": "ToDo",
			"name": "on-the-device-1",
			"values": {"description": "Register the request", "owner": "Guest", "docstatus": 1},
		}
		update = {
			"change_id": "update-1",
			"operation": "Update",
			"doctype": "ToDo",
			"name": "on-the-device-1",
			"fields": {"priority": {"from": "Medium", "to": "High"}},
		}
		created, updated = self.send(create, update)
		self.assertEqual((created.status, created.situation), ("Applied", "New record"))
		# ToDo is named by the server: the later change finds the record under the server's name
		self.assertNotEqual(created.applied_to, "on-the-device-1")
		self.assertEqual(
			(updated.status, updated.situation, updated.applied_to),
			("Applied", "Unchanged", created.applied_to),
		)
		todo = frappe.get_doc("ToDo", created.applied_to)
		self.assertEqual((todo.priority, todo.owner, todo.docstatus), ("High", "Administrator", 0))
		self.assertEqual(status(["create-1"])["create-1"]["name"], created.applied_to)

	def test_a_change_waits_for_the_creation_it_depends_on(self):
		create = {
			"change_id": "create-2",
			"operation": "Create",
			"doctype": "ToDo",
			"name": "on-the-device-2",
			"values": {"description": "Register the request", "status": "Not a status"},
		}
		update = {
			"change_id": "update-2",
			"operation": "Update",
			"doctype": "ToDo",
			"name": "on-the-device-2",
			"fields": {"priority": {"from": "Medium", "to": "High"}},
		}
		created, updated = self.send(create, update)
		self.assertEqual(created.status, "Failed")
		self.assertEqual((updated.status, updated.depends_on), ("Held", created.name))

	# Tables

	def test_rows_are_changed_added_and_removed(self):
		contact = frappe.get_doc({"doctype": "Contact", "first_name": "Amina"})
		for address in ("amina@example.org", "amina.work@example.org", "old@example.org"):
			contact.append(
				"email_ids", {"email_id": address, "is_primary": int(address == "amina@example.org")}
			)
		contact.insert()
		_first, work, old = contact.email_ids
		device = {
			**self.update(contact, last_name=(None, "Diallo")),
			"rows": {
				"email_ids": {
					"changed": {
						work.name: {
							"email_id": {"from": "amina.work@example.org", "to": "a.diallo@example.org"}
						}
					},
					"added": [{"email_id": "new@example.org", "parent": "another-contact"}],
					"removed": [old.name],
				}
			},
		}
		(change,) = self.send(device)
		self.assertEqual(change.status, "Applied", change.message)
		self.assertEqual(
			{row.fieldname: row.table_field for row in change.field_changes},
			{"last_name": None, "email_id": "email_ids"},
		)
		contact.reload()
		self.assertEqual(contact.last_name, "Diallo")
		self.assertEqual(
			sorted(row.email_id for row in contact.email_ids),
			["a.diallo@example.org", "amina@example.org", "new@example.org"],
		)

	def test_a_row_removed_on_the_server_holds_the_change(self):
		contact = frappe.get_doc({"doctype": "Contact", "first_name": "Amina"})
		contact.append("email_ids", {"email_id": "amina@example.org", "is_primary": 1})
		contact.append("email_ids", {"email_id": "amina.work@example.org"})
		contact.insert()
		work = contact.email_ids[1]
		device = {
			"change_id": "row-1",
			"operation": "Update",
			"doctype": "Contact",
			"name": contact.name,
			"base_modified": str(contact.modified),
			"rows": {
				"email_ids": {
					"changed": {
						work.name: {"email_id": {"from": "amina.work@example.org", "to": "a@example.org"}}
					}
				}
			},
		}
		server = frappe.get_doc("Contact", contact.name)
		server.remove(server.email_ids[1])
		server.save()
		(change,) = self.send(device)
		self.assertEqual(change.status, "Held")
		change.field_changes[0].resolution = "Server"
		self.assertTrue(change.resolve())

	# What a device may send

	def test_a_batch_sent_twice_is_applied_once(self):
		todo = self.todo()
		device = self.update(todo, priority=("Medium", "High"))
		self.send(device)
		frappe.db.set_value("ToDo", todo.name, "priority", "Low")
		again = submit(changes=[device], device_id="tablet-1")
		self.assertEqual(again["changes"][device["change_id"]], "Applied")
		processing.process_batch(again["batch_id"])
		self.assertEqual(self.value(todo, "priority"), "Low")
		self.assertEqual(frappe.db.count("Offline Change", {"change_id": device["change_id"]}), 1)

	def test_a_change_the_user_may_not_make_is_refused_and_kept(self):
		todo = self.todo()
		user = self.user("field.officer@example.org")
		device = self.update(todo, priority=("Medium", "High"))
		frappe.set_user(user.name)
		(change,) = self.send(device)
		self.assertEqual((change.status, change.situation, change.user), ("Refused", "No access", user.name))
		self.assertEqual(change.field_changes[0].device_value, "High")
		self.assertEqual(self.value(todo, "priority"), "Medium")
		self.assertEqual(status([device["change_id"]])[device["change_id"]]["status"], "Refused")
		# The change belongs to the user who sent it: nobody else sends it again, or asks about it
		frappe.set_user("Administrator")
		self.assertEqual(status([device["change_id"]]), {})
		self.assertRaises(frappe.PermissionError, submit, changes=[device], device_id="tablet-2")

	def test_a_doctype_not_opened_to_devices_is_refused_and_kept(self):
		note = {
			"change_id": "note-1",
			"operation": "Create",
			"doctype": "Note",
			"values": {"title": "Field note"},
		}
		(change,) = self.send(note)
		self.assertEqual(change.status, "Refused")
		self.assertFalse(frappe.db.exists("Note", {"title": "Field note"}))

	def test_a_batch_built_wrongly_is_not_recorded(self):
		todo = self.todo()
		good = self.update(todo, priority=("Medium", "High"))
		for wrong in (
			{**good, "change_id": None},
			{**good, "operation": "Merge"},
			{**good, "doctype": "No Such DocType"},
			{**good, "name": None},
			{**good, "base_modified": "yesterday"},
			{**good, "fields": ["priority"]},
			{**good, "fields": {}},
		):
			self.assertRaises(frappe.ValidationError, submit, changes=[good, wrong], device_id="tablet-1")
		self.assertRaises(frappe.ValidationError, submit, changes=[good] * 51, device_id="tablet-1")
		frappe.db.set_single_value("Offline Change Settings", "enabled", 0)
		self.assertRaises(frappe.ValidationError, submit, changes=[good], device_id="tablet-1")

	# Rules, scopes and reviewers

	def test_the_narrowest_rule_decides(self):
		general = find_rule("Same field changed", "ToDo", "priority")
		self.assertEqual(general.outcome, "Last to arrive wins")
		for_doctype = self.rule("Same field changed", "Server value stays", reference_doctype="ToDo")
		for_field = self.rule(
			"Same field changed", "Hold for review", reference_doctype="ToDo", fieldname="priority"
		)
		for_scope = self.rule(
			"Same field changed", "Server value stays", scope_doctype="Role", scope_name="Guest"
		)
		self.assertEqual(find_rule("Same field changed", "Contact", "phone").name, general.name)
		self.assertEqual(find_rule("Same field changed", "ToDo", "date").name, for_doctype.name)
		self.assertEqual(find_rule("Same field changed", "ToDo", "priority").name, for_field.name)
		self.assertEqual(
			find_rule("Same field changed", "ToDo", "priority", ("Role", "Guest")).name, for_scope.name
		)
		for_field.enabled = 0
		for_field.save()
		self.assertEqual(find_rule("Same field changed", "ToDo", "priority").name, for_doctype.name)

	def test_a_rule_is_checked(self):
		self.assertRaises(frappe.ValidationError, self.rule, "Same field changed", "Merge")
		self.assertRaises(
			frappe.ValidationError,
			self.rule,
			"Same field changed",
			"Hold for review",
			reference_doctype="ToDo",
			fieldname="no_such_field",
		)
		self.assertRaises(
			frappe.ValidationError,
			self.rule,
			"Different fields changed",
			"Merge",
			reference_doctype="ToDo",
			fieldname="priority",
		)
		self.assertRaises(frappe.ValidationError, self.rule, "Different fields changed", "Hold for review")
		self.assertRaises(
			frappe.ValidationError, self.rule, "Same field changed", "Hold for review", scope_doctype="Role"
		)
		self.rule("Same field changed", "Hold for review", reference_doctype="Contact", fieldname="email_id")

	def test_a_scope_narrows_the_rule_and_the_reviewers(self):
		with self.patch_hooks(HOOKS):
			self.rule("Same field changed", "Hold for review", scope_doctype="Role", scope_name="Guest")
			held, applied = self.todo(role="Guest"), self.todo(role="Desk User")
			devices = [self.update(todo, priority=("Medium", "High")) for todo in (held, applied)]
			for todo in (held, applied):
				frappe.get_doc("ToDo", todo.name).update({"priority": "Low"}).save()
			in_guest, in_desk = self.send(*devices)
			self.assertEqual((in_guest.status, in_guest.scope_name), ("Held", "Guest"))
			self.assertEqual((in_desk.status, in_desk.scope_name), ("Applied", "Desk User"))

			reviewer = self.user("reviewer.one@example.org", "Offline Change Reviewer")
			REVIEWS.append(("Role", "Guest"))
			self.assertTrue(frappe.has_permission("Offline Change", "write", in_guest, user=reviewer.name))
			self.assertFalse(frappe.has_permission("Offline Change", "read", in_desk, user=reviewer.name))
			frappe.set_user(reviewer.name)
			listed = frappe.get_list(
				"Offline Change", filters={"name": ("in", [in_guest.name, in_desk.name])}, pluck="name"
			)
			self.assertEqual(listed, [in_guest.name])
			self.assertEqual(query_conditions("Administrator"), "")

	def open_to_devices(self, **named):
		"""Settings as an administrator would write them: ToDo with its fields named, and Language."""
		settings = frappe.get_single("Offline Change Settings")
		settings.set(
			"doctypes",
			[
				{
					"reference_doctype": "ToDo",
					"allow_create": 1,
					"allow_update": 1,
					"allow_delete": 1,
					"scope_field": "role",
				},
				{"reference_doctype": "Language", "allow_update": 1, **named},
			],
		)
		settings.save()
		return settings

	def test_the_settings_name_the_scope_of_a_record(self):
		self.open_to_devices()
		self.rule("Same field changed", "Hold for review", scope_doctype="Role", scope_name="Guest")
		held, applied = self.todo(role="Guest"), self.todo()
		devices = [self.update(todo, priority=("Medium", "High")) for todo in (held, applied)]
		for todo in (held, applied):
			frappe.get_doc("ToDo", todo.name).update({"priority": "Low"}).save()
		in_guest, without = self.send(*devices)
		self.assertEqual(
			(in_guest.status, in_guest.scope_doctype, in_guest.scope_name), ("Held", "Role", "Guest")
		)
		self.assertEqual((without.status, without.scope_name), ("Applied", None))

		created = {
			"change_id": "scoped-1",
			"operation": "Create",
			"doctype": "ToDo",
			"values": {"description": "New", "role": "Guest"},
		}
		self.assertEqual(self.send(created)[0].scope_name, "Guest")

	def test_a_deleted_record_keeps_its_scope(self):
		self.open_to_devices()
		todo = self.todo(role="Guest")
		device = self.update(todo, priority=("Medium", "High"))
		frappe.delete_doc("ToDo", todo.name)
		(change,) = self.send(device)
		# Read from what Frappe kept of the deleted record, not from the device
		self.assertEqual((change.status, change.scope_name), ("Held", "Guest"))

		# Where nothing is left of the record, the device's belief is taken, for a scope that exists
		frappe.db.delete("Deleted Document", {"deleted_name": todo.name})
		for change_id, believed, found in (("gone-1", "Guest", "Guest"), ("gone-2", "No Such Role", None)):
			(change,) = self.send({**device, "change_id": change_id, "scope": believed})
			self.assertEqual(change.scope_name, found)
		# A record that exists is never placed by what the device says
		(change,) = self.send(
			{**self.update(self.todo(role="Guest"), priority=("Medium", "High")), "scope": "Desk User"}
		)
		self.assertEqual(change.scope_name, "Guest")

	def test_the_settings_name_the_field_of_the_replacement(self):
		self.open_to_devices(replaced_by_field="based_on")
		for code, based_on in (("zzc", None), ("zzb", "zzc"), ("zza", "zzb")):
			frappe.get_doc(
				{"doctype": "Language", "language_code": code, "language_name": code, "based_on": based_on}
			).insert()
		merged = frappe.get_doc("Language", "zza")
		(change,) = self.send(self.update(merged, flag=(None, "zz")))
		# zza was replaced by zzb, itself replaced by zzc: the change lands on the record that remains
		self.assertEqual(
			(change.status, change.situation, change.applied_to),
			("Applied", "Record replaced on server", "zzc"),
			change.message,
		)
		self.assertEqual(frappe.db.get_value("Language", "zzc", "flag"), "zz")
		self.assertIsNone(frappe.db.get_value("Language", "zza", "flag"))

	def test_the_fields_named_in_the_settings_are_checked(self):
		settings = self.open_to_devices()
		for named in (
			{"scope_field": "no_such_field"},
			{"scope_field": "description"},
			{"replaced_by_field": "role"},
		):
			settings.doctypes[0].update({"scope_field": "role", "replaced_by_field": None, **named})
			self.assertRaises(frappe.ValidationError, settings.save)

	def test_a_reviewer_sees_the_scopes_listed_for_them(self):
		self.open_to_devices()
		todos = [self.todo(role="Guest"), self.todo(role="Desk User"), self.todo()]
		in_guest, in_desk, without = self.send(
			*[self.update(todo, priority=("Medium", "High")) for todo in todos]
		)
		reviewer = self.user("reviewer.two@example.org", "Offline Change Reviewer")

		def seen():
			frappe.set_user(reviewer.name)
			names = frappe.get_list(
				"Offline Change",
				filters={"name": ("in", [in_guest.name, in_desk.name, without.name])},
				pluck="name",
			)
			allowed = {
				change.name
				for change in (in_guest, in_desk, without)
				if frappe.has_permission("Offline Change", "write", change)
			}
			frappe.set_user("Administrator")
			self.assertEqual(set(names), allowed)
			return allowed

		# Listed for no scope, a reviewer sees nothing: not even a change that has no scope
		self.assertEqual(seen(), set())
		listed = {
			"doctype": "Offline Review Scope",
			"user": reviewer.name,
			"scope_doctype": "Role",
			"scope_name": "Guest",
		}
		frappe.get_doc(listed).insert()
		self.assertRaises(frappe.ValidationError, frappe.get_doc(listed).insert)
		self.assertEqual(seen(), {in_guest.name})
		frappe.db.set_single_value("Offline Change Settings", "reviewers_see_unscoped", 1)
		self.assertEqual(seen(), {in_guest.name, without.name})

	def test_applied_values_are_removed_after_the_period(self):
		todo = self.todo()
		clean = self.update(todo, date=(str(todo.date), "2026-12-05"))
		(applied,) = self.send(clean)
		lost_device = self.update(frappe.get_doc("ToDo", todo.name), priority=("Medium", "High"))
		frappe.get_doc("ToDo", todo.name).update({"priority": "Low"}).save()
		(lost,) = self.send(lost_device)
		recent = self.send(self.update(frappe.get_doc("ToDo", todo.name), color=(None, "#ff0000")))[0]
		long_ago = add_days(now_datetime(), -31)
		for change in (applied, lost):
			frappe.db.set_value("Offline Change", change.name, "modified", long_ago, update_modified=False)
		remove_old_values()
		for change in (applied, lost, recent):
			change.reload()
		self.assertEqual(
			(applied.values_removed, applied.payload, applied.field_changes[0].device_value), (1, None, None)
		)
		self.assertEqual(applied.field_changes[0].fieldname, "date")
		# A value that lost stays until a reviewer has closed the change
		self.assertEqual((lost.values_removed, lost.field_changes[0].server_value), (0, "Low"))
		self.assertEqual(recent.values_removed, 0)
		lost.close()
		frappe.db.set_value("Offline Change", lost.name, "modified", long_ago, update_modified=False)
		remove_old_values()
		self.assertEqual(frappe.db.get_value("Offline Change", lost.name, "values_removed"), 1)
