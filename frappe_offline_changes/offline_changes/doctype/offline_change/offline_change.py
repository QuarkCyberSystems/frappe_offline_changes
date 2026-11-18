"""The queue of changes captured offline: what each device sent, and what became of it.

A row is written when a device sends a change (frappe_offline_changes.api.changes) and completed when the
change is processed (frappe_offline_changes.offline_changes.processing). Nobody enters or edits one by hand:
a reviewer only chooses, per field in conflict, which value the record keeps, then resolves, rejects or
closes the change.

A row holds values of the record it concerns, so it is seen only by those who review that record's scope
(frappe_offline_changes.utils.extensions), and the values of a change that was applied are removed after the
period set in Offline Change Settings: the record's own history keeps them. A value that lost stays until a
reviewer closes the change.
"""

import frappe
from frappe import _
from frappe.model import no_value_fields, table_fields
from frappe.model.document import Document
from frappe.utils import add_days, now_datetime

from frappe_offline_changes.offline_changes import processing
from frappe_offline_changes.utils.extensions import reviewer_scopes

# What a reviewer may set on a row: everything else is what the device sent and what the module recorded
REVIEWER_FIELDS = ("resolution", "resolved_value")
VALUE_FIELDS = ("base_value", "device_value", "server_value", "resolved_value")


class OfflineChange(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from frappe_offline_changes.offline_changes.doctype.offline_change_field.offline_change_field import (
			OfflineChangeField,
		)

		applied_to: DF.Data | None
		base_modified: DF.Datetime | None
		batch_id: DF.Data | None
		batch_index: DF.Int
		captured_on: DF.Datetime | None
		change_id: DF.Data
		closed: DF.Check
		depends_on: DF.Link | None
		device_id: DF.Data | None
		field_changes: DF.Table[OfflineChangeField]
		has_lost_values: DF.Check
		message: DF.SmallText | None
		operation: DF.Literal["Create", "Update", "Delete"]
		payload: DF.JSON | None
		received_on: DF.Datetime | None
		reference_doctype: DF.Link
		reference_name: DF.Data | None
		resolved_by: DF.Link | None
		resolved_on: DF.Datetime | None
		rule: DF.Link | None
		scope_doctype: DF.Link | None
		scope_name: DF.DynamicLink | None
		situation: DF.Literal[
			"",
			"Unchanged",
			"Different fields changed",
			"Same field changed",
			"Changed on device, deleted on server",
			"Record replaced on server",
			"Deleted on device, changed on server",
			"New record",
			"No access",
		]
		status: DF.Literal["Received", "Applied", "Held", "Refused", "Failed", "Resolved", "Rejected"]
		user: DF.Link
		values_removed: DF.Check
	# end: auto-generated types

	def validate(self):
		if self.flags.from_module:
			return
		if self.is_new():
			frappe.throw(_("A change is received from a device, not entered here"))
		self.keep_as_received(self.get_doc_before_save())

	def keep_as_received(self, stored):
		"""Put back everything but the reviewer's choices, so the record of what was sent cannot be edited."""
		for df in self.meta.fields:
			if df.fieldtype not in no_value_fields + table_fields:
				self.set(df.fieldname, stored.get(df.fieldname))
		rows = {row.name: row for row in stored.field_changes}
		if {row.name for row in self.field_changes} != set(rows):
			frappe.throw(_("The fields of a change cannot be added or removed"))
		for row in self.field_changes:
			for df in row.meta.fields:
				if df.fieldname not in REVIEWER_FIELDS and df.fieldtype not in no_value_fields:
					row.set(df.fieldname, rows[row.name].get(df.fieldname))

	def on_trash(self):
		if frappe.session.user != "Administrator":
			frappe.throw(_("A change received from a device is kept as a record and cannot be deleted"))

	@frappe.whitelist()
	def resolve(self) -> bool:
		"""Apply the change with the reviewer's choices, as the reviewer."""
		self.check_waiting()
		if self.values_removed:
			frappe.throw(_("The values of this change were removed and it can no longer be applied"))
		if processing.resolve(self):
			return True
		frappe.msgprint(
			_(
				"The record changed again on the server. Choose a value for each field in conflict, then resolve."
			)
		)
		return False

	@frappe.whitelist()
	def reject(self, reason: str):
		"""Close the change without applying it."""
		self.check_waiting()
		if not (reason or "").strip():
			frappe.throw(_("Give the reason for rejecting the change"))
		self.status, self.message = "Rejected", reason.strip()
		self.resolved_by, self.resolved_on = frappe.session.user, now_datetime()
		self.save_as_module()

	@frappe.whitelist()
	def close(self):
		"""Mark as seen the values that lost, so they are removed with the others."""
		self.check_reviewer()
		if not self.has_lost_values or self.status in processing.OPEN:
			frappe.throw(_("Only a change that was applied over another value is closed"))
		self.closed = 1
		self.save_as_module()

	def save_as_module(self):
		self.flags.from_module = True
		# The rule that decided, or the user who sent, may be gone by now: the row still records them
		self.flags.ignore_links = True
		self.save()

	def check_reviewer(self):
		"""The form sends the document with the call: only its choices are taken from it."""
		self.keep_as_received(frappe.get_doc(self.doctype, self.name))
		self.check_permission("write")

	def check_waiting(self):
		self.check_reviewer()
		if self.status not in processing.REVIEWABLE:
			frappe.throw(_("This change is {0} and does not wait for a reviewer").format(_(self.status)))


def has_permission(doc, ptype=None, user=None) -> bool:
	"""A reviewer handles the changes of their scopes. One without a scope is theirs only where the site says so."""
	user = user or frappe.session.user
	if _sees_all(user):
		return True
	if not doc.scope_name:
		return _unscoped_shown()
	return (doc.scope_doctype, doc.scope_name) in reviewer_scopes(user)


def query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	scopes = reviewer_scopes(user)
	unscoped = "ifnull(`tabOffline Change`.scope_name, '') = ''" if _unscoped_shown() else "1 = 0"
	if not scopes:
		return unscoped
	pairs = ", ".join(
		f"({frappe.db.escape(scope_doctype)}, {frappe.db.escape(scope_name)})"
		for scope_doctype, scope_name in scopes
	)
	# A permission hook returns a condition as text, so the values cannot be parameters: each is escaped above
	return f"({unscoped} or (`tabOffline Change`.scope_doctype, `tabOffline Change`.scope_name) in ({pairs}))"


def has_app_permission() -> bool:
	"""The app is shown to those who review changes or configure it."""
	return bool({"System Manager", "Offline Change Reviewer"} & set(frappe.get_roles()))


def _sees_all(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _unscoped_shown() -> bool:
	return bool(frappe.db.get_single_value("Offline Change Settings", "reviewers_see_unscoped"))


def remove_old_values():
	"""Daily: remove the values of the changes that were dealt with long enough ago."""
	days = frappe.db.get_single_value("Offline Change Settings", "keep_values_days")
	if not days:
		return
	# The scheduler acts for the site, not for a reviewer: the queue is read whole
	for name in frappe.get_all(
		"Offline Change",
		filters={
			"status": ("in", ("Applied", "Resolved", "Rejected")),
			"values_removed": 0,
			"modified": ("<", add_days(now_datetime(), -days)),
		},
		or_filters={"has_lost_values": 0, "closed": 1},
		pluck="name",
	):
		change = frappe.get_doc("Offline Change", name)
		change.payload = None
		for row in change.field_changes:
			for fieldname in VALUE_FIELDS:
				row.set(fieldname, None)
		change.values_removed = 1
		change.flags.from_module = True
		change.save(ignore_permissions=True)
