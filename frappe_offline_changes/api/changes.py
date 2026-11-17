"""What a device calls: send the changes it captured offline, and ask what became of them.

Both calls are made by the signed-in user. A device shared by several people sends each person's changes
in that person's own session: a change is recorded, and later applied, as the user who sent it.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from frappe_offline_changes.offline_changes.processing import field_rows
from frappe_offline_changes.utils.extensions import scope_of

OPERATIONS = ("Create", "Update", "Delete")


@frappe.whitelist(methods=["POST"])
def submit(changes: list | str, device_id: str, batch_id: str | None = None) -> dict:
	"""Record a batch of changes, in the order captured, and queue it to be applied.

	Each change: `change_id` (generated on the device, so a batch sent twice is applied once), `operation`
	(Create, Update, Delete), `doctype`, `name`, `captured_on`, `scope` (the business unit the device believes
	the record belongs to, used only if the record is gone), `base_modified` (the record's `modified` when
	the device read it; empty for a record the device created and has not sent yet) and the payload described in
	frappe_offline_changes.offline_changes.processing.

	Returns the batch and, per change id, its status: Received, or what a change sent before has become."""
	settings = frappe.get_single("Offline Change Settings")
	if not settings.enabled:
		frappe.throw(_("This site does not receive changes captured offline"))
	changes = frappe.parse_json(changes) if isinstance(changes, str) else changes
	if settings.max_batch_size and len(changes) > settings.max_batch_size:
		frappe.throw(_("A batch holds at most {0} changes").format(settings.max_batch_size))

	batch_id = batch_id or frappe.generate_hash(length=16)
	statuses, received = {}, False
	for index, change in enumerate(changes):
		change = _checked(frappe._dict(change), index)
		# The queue is read and written here for its own author: users hold no right on the queue itself
		sent_before = frappe.db.get_value(
			"Offline Change", {"change_id": change.change_id}, ["user", "status"], as_dict=True
		)
		if sent_before:
			if sent_before.user != frappe.session.user:
				frappe.throw(
					_("Change {0} was sent by another user").format(change.change_id), frappe.PermissionError
				)
			statuses[change.change_id] = sent_before.status
			continue

		payload = {key: change[key] for key in ("values", "fields", "rows") if change.get(key)}
		# Found now, while the sender is known and the record most likely still exists, so that a change refused
		# below, or one whose record is deleted before the job runs, still reaches the right reviewers
		scope = scope_of(change.doctype, change.get("name"), change.get("values"), hint=change.get("scope"))
		doc = frappe.get_doc(
			{
				"doctype": "Offline Change",
				"change_id": change.change_id,
				"device_id": device_id,
				"batch_id": batch_id,
				"batch_index": index,
				"user": frappe.session.user,
				"operation": change.operation,
				"reference_doctype": change.doctype,
				"reference_name": change.get("name"),
				"base_modified": change.get("base_modified"),
				"captured_on": change.get("captured_on"),
				"received_on": now_datetime(),
				"scope_doctype": scope and scope[0],
				"scope_name": scope and scope[1],
				"payload": frappe.as_json(payload, indent=None),
				"field_changes": field_rows(change.doctype, payload) if change.operation == "Update" else [],
			}
		)
		if not settings.allows(change.doctype, change.operation):
			# Kept all the same, so that what was captured is not lost: a reviewer sees it
			doc.status = "Refused"
			doc.message = _("{0} may not be sent from a device: {1}").format(
				_(change.doctype), _(change.operation)
			)
		doc.flags.from_module = True
		doc.insert(ignore_permissions=True)
		statuses[change.change_id] = doc.status
		received = received or doc.status == "Received"

	if received:
		frappe.enqueue(
			"frappe_offline_changes.offline_changes.processing.process_batch",
			batch_id=batch_id,
			enqueue_after_commit=True,
		)
	return {"batch_id": batch_id, "changes": statuses}


@frappe.whitelist()
def status(change_ids: list | str) -> dict:
	"""What became of the session user's changes: per change id, the status, why, and the record's name."""
	change_ids = frappe.parse_json(change_ids) if isinstance(change_ids, str) else change_ids
	if not change_ids:
		return {}
	# A user asks about their own changes only, which the filter on the user ensures
	changes = frappe.get_all(
		"Offline Change",
		filters={"change_id": ("in", change_ids), "user": frappe.session.user},
		fields=["name", "change_id", "status", "situation", "message", "reference_name", "applied_to"],
	)
	outcomes = {}
	for row in frappe.get_all(
		"Offline Change Field",
		filters={"parent": ("in", [change.name for change in changes]), "parenttype": "Offline Change"},
		fields=["parent", "fieldname", "table_field", "row_name", "outcome"],
		order_by="idx asc",
	):
		outcomes.setdefault(row.pop("parent"), []).append(row)
	return {
		change.change_id: {
			"status": change.status,
			"situation": change.situation,
			"message": change.message,
			"name": change.applied_to or change.reference_name,
			"fields": outcomes.get(change.name, []),
		}
		for change in changes
	}


def _checked(change: frappe._dict, index: int) -> frappe._dict:
	"""A change a device built wrongly stops the batch: nothing of it is recorded, and the device is told."""

	def refuse(message):
		frappe.throw(_("Change {0}: {1}").format(index + 1, message))

	if not change.get("change_id") or not isinstance(change.change_id, str):
		refuse(_("it has no change id"))
	if change.get("operation") not in OPERATIONS:
		refuse(_("its operation is not Create, Update or Delete"))
	if not change.get("doctype") or not frappe.db.exists("DocType", change.doctype):
		refuse(_("it names no DocType of this site"))
	if change.operation != "Create":
		if not change.get("name"):
			refuse(_("it does not name the record"))
		try:
			get_datetime(change.get("base_modified"))
		except Exception:
			refuse(_("the version of the record the device read is not a date and time"))
	for key in ("values", "fields", "rows"):
		if change.get(key) and not isinstance(change[key], dict):
			refuse(_("its {0} are not given by name").format(key))
	if change.operation == "Create" and not change.get("values"):
		refuse(_("it has no values for the record to create"))
	if change.operation == "Update" and not (change.get("fields") or change.get("rows")):
		refuse(_("it changes nothing"))
	return change
