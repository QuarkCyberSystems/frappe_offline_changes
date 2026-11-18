"""Applying what a device captured offline.

A change is one record and one operation. For an update the device sends, per field, the value it started
from and the new one, so each field is judged on its own against the value the server holds now:

        server = started from   nobody else changed it: the device's value is applied
        server = device         both sides made the same change: nothing to do
        otherwise               a conflict on this field

What follows is decided by the Conflict Rules, except three outcomes that are never rules: a change the
user may not make is refused, a change that fails the record's own validation is kept as failed, and a
deletion of a record changed since is held. A change is applied whole or not at all: one field held for
review holds the others with it, so a record is never left half changed.

A change is applied as the user who sent it (the background job runs as that user), with the rights that
user has when it arrives, not those of the day it was captured. A reviewer resolving a held change applies
it with their own.

What a device sends (`payload`):

        {"values": {...}}                                    a record to create
        {"fields": {fieldname: {"from": ..., "to": ...}},    an update: the record's own fields
         "rows": {table_field: {"added": [{...}],            and its child tables
                                "changed": {row_name: {fieldname: {"from": ..., "to": ...}}},
                                "removed": [row_name]}}}
"""

import frappe
from frappe import _
from frappe.model import child_table_fields, default_fields, no_value_fields, numeric_fieldtypes, table_fields
from frappe.utils import cast_fieldtype, cstr, flt, get_datetime, now_datetime
from frappe.utils.messages import clear_messages

from frappe_offline_changes.offline_changes.doctype.conflict_rule.conflict_rule import HOLD, find_rule
from frappe_offline_changes.utils.extensions import extension, replaced_by, scope_of

SAVEPOINT = "offline_change"
# A change in one of these statuses still waits: for the job, or for a reviewer
OPEN = ("Received", "Held", "Refused", "Failed")
REVIEWABLE = ("Held", "Refused", "Failed")

UNCHANGED = "Unchanged"
DIFFERENT_FIELDS = "Different fields changed"
SAME_FIELD = "Same field changed"
DELETED_ON_SERVER = "Changed on device, deleted on server"
REPLACED = "Record replaced on server"
DELETED_ON_DEVICE = "Deleted on device, changed on server"
NEW = "New record"
NO_ACCESS = "No access"


def process_batch(batch_id: str):
	"""Apply the changes of a batch the session user sent, in the order they were captured."""
	# The queue is read here for its own author: users hold no right on the queue itself
	for name in frappe.get_all(
		"Offline Change",
		filters={"batch_id": batch_id, "status": "Received", "user": frappe.session.user},
		order_by="batch_index asc",
		pluck="name",
	):
		process(frappe.get_doc("Offline Change", name))


def process_waiting(names: list[str]):
	"""Apply the changes that waited for another one, each as the user who sent it."""
	session_user = frappe.session.user
	try:
		for name in names:
			change = frappe.get_doc("Offline Change", name)
			if change.status != "Received":
				continue
			# The change was authenticated as this user when the device sent it, and is applied with the rights it
			# would have had in its own batch
			# nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser -- reviewed: the user is read from the queue row, which only this module writes, and the session user is restored below
			frappe.set_user(change.user)
			process(change)
	finally:
		# nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser -- reviewed: restores the user the job started as
		frappe.set_user(session_user)


def process(change):
	"""Apply one received change as the session user, and record what became of it."""
	frappe.db.savepoint(SAVEPOINT)
	try:
		_apply(change)
	except frappe.PermissionError as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		change.situation = NO_ACCESS
		_stop(change, "Refused", cstr(error) or _("You may not make this change"))
	except Exception as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		_stop(change, "Failed", cstr(error))
	finally:
		# What the record's own validation said is kept on the change, not shown to whoever runs the job
		clear_messages()
	_save(change)


def resolve(change) -> bool:
	"""Apply a waiting change as the reviewer, with the reviewer's choices.

	False when the server's values moved again and a conflict has no choice yet: the rows are brought up to
	date and nothing is applied."""
	_apply(change, reviewing=True)
	if change.status == "Resolved":
		change.resolved_by, change.resolved_on = frappe.session.user, now_datetime()
	_save(change)
	if change.flags.choice_missing:
		return False
	_release(change)
	return True


def field_rows(doctype: str, payload: dict) -> list[dict]:
	"""The rows of a change: one per field the device changed, in the record and in its child tables."""
	meta = frappe.get_meta(doctype)
	rows = [_field_row(meta, fieldname, pair) for fieldname, pair in (payload.get("fields") or {}).items()]
	for table_field, operations in (payload.get("rows") or {}).items():
		table = meta.get_field(table_field)
		child = frappe.get_meta(table.options) if table and table.fieldtype in table_fields else None
		for row_name, fields in (operations.get("changed") or {}).items():
			rows += [
				_field_row(child, fieldname, pair, table_field, row_name)
				for fieldname, pair in fields.items()
			]
	return rows


def _field_row(meta, fieldname, pair, table_field=None, row_name=None) -> dict:
	df = meta.get_field(fieldname) if meta else None
	return {
		"fieldname": fieldname,
		"label": df.label if df and df.label else fieldname,
		"table_field": table_field,
		"row_name": row_name,
		"base_value": _text(pair.get("from")),
		"device_value": _text(pair.get("to")),
	}


def _apply(change, reviewing=False):
	payload = frappe.parse_json(change.payload or "{}")
	name = change.reference_name
	if change.operation != "Create":
		created = _created_offline(change.reference_doctype, name)
		if created and created.name != change.name:
			if created.status in OPEN:
				return _hold(
					change, _("The record this change is for has not been created yet"), created.name
				)
			# A record the server named itself is found under that name, not the device's
			name = created.applied_to or name
	{"Create": _create, "Update": _update, "Delete": _delete}[change.operation](
		change, payload, name, reviewing
	)


def _create(change, payload, name, reviewing):
	doctype = change.reference_doctype
	values = _plain(payload.get("values") or {})
	change.situation = NEW
	_set_scope(change, None, values)
	if name and frappe.db.exists(doctype, name):
		frappe.throw(_("A record named {0} already exists").format(name))
	waits_for = _point_links(frappe.get_meta(doctype), values)
	if waits_for:
		return _hold(change, _("A record this one refers to has not been created yet"), waits_for)

	doc = frappe.get_doc({"doctype": doctype, **values})
	if name:
		# Kept by Frappe where the DocType is named by UUID or by hand; replaced by the server's name elsewhere
		doc.name = name
	custom = extension(doctype, "apply")
	if custom:
		custom(doc=doc, values=values, rows={}, change=change)
	else:
		doc.insert()
	change.applied_to = doc.name
	_stop(change, "Resolved" if reviewing else "Applied")
	after_create = extension(doctype, "after_create")
	if after_create:
		after_create(doc=doc, change=change)


def _delete(change, payload, name, reviewing):
	doctype = change.reference_doctype
	if not frappe.db.exists(doctype, name):
		change.situation = change.situation or UNCHANGED
		return _stop(change, "Resolved" if reviewing else "Applied", _("The record was already deleted"))
	doc = frappe.get_doc(doctype, name)
	_set_scope(change, name)
	if not reviewing and _moved(change, doc):
		change.situation = DELETED_ON_DEVICE
		return _hold(change, _("The record was changed on the server after the device read it"))
	change.situation = change.situation or UNCHANGED
	frappe.delete_doc(doctype, name)
	change.applied_to = name
	_stop(change, "Resolved" if reviewing else "Applied")


def _update(change, payload, name, reviewing):
	doctype = change.reference_doctype
	scope = _set_scope(change, name)

	successor = replaced_by(doctype, name)
	if successor:
		rule = find_rule(REPLACED, doctype, scope=scope)
		change.situation, change.rule = REPLACED, rule and rule.name
		if not reviewing and (not rule or rule.outcome == HOLD):
			return _hold(change, _("The record was replaced by {0} on the server").format(successor))
		name = successor
		scope = _set_scope(change, name)

	if not frappe.db.exists(doctype, name):
		if reviewing:
			frappe.throw(_("The record no longer exists. Reject the change."))
		rule = find_rule(DELETED_ON_SERVER, doctype, scope=scope)
		change.situation, change.rule = DELETED_ON_SERVER, rule and rule.name
		if rule and rule.outcome == "Deletion stands":
			change.has_lost_values = 1
			return _stop(
				change,
				"Rejected",
				_("The record was deleted on the server, and the rule lets the deletion stand"),
			)
		return _hold(change, _("The record was deleted on the server"))

	doc = frappe.get_doc(doctype, name)
	if not doc.has_permission("write"):
		raise frappe.PermissionError(_("You may not change this record"))
	entries = _compare(change, doc, payload)
	conflicts = [entry for entry in entries if entry.row.conflict]

	if reviewing:
		if any(not entry.row.resolution for entry in conflicts):
			change.flags.choice_missing = True
			return
	elif conflicts:
		change.situation = SAME_FIELD
		for entry in conflicts:
			rule = find_rule(SAME_FIELD, doctype, entry.row.fieldname, scope)
			entry.row.rule, entry.decision = rule and rule.name, rule.outcome if rule else HOLD
		held = [entry for entry in conflicts if entry.decision == HOLD or entry.target is None]
		if held:
			for entry in conflicts:
				entry.row.outcome = "Held"
			change.rule = held[0].row.rule
			return _hold(change, _("A field was changed on the server after the device read it"))
		change.rule, change.has_lost_values = conflicts[0].row.rule, 1
	elif _moved(change, doc) and change.situation != REPLACED:
		rule = find_rule(DIFFERENT_FIELDS, doctype, scope=scope)
		change.situation, change.rule = DIFFERENT_FIELDS, rule and rule.name
		if not rule or rule.outcome == HOLD:
			return _hold(
				change, _("Other fields of the record were changed on the server after the device read it")
			)
	else:
		change.situation = change.situation or UNCHANGED

	values, rows = _chosen(entries, reviewing)
	waits_for = _point_links(doc.meta, values)
	if waits_for:
		return _hold(change, _("A record this one refers to has not been created yet"), waits_for)
	for table_field, operations in (payload.get("rows") or {}).items():
		_table(doc.meta, table_field)
		for kind in ("added", "removed"):
			if operations.get(kind):
				rows.setdefault(table_field, {})[kind] = operations[kind]
	_save_record(doc, values, rows, change)
	change.applied_to = doc.name
	_stop(change, "Resolved" if reviewing else "Applied")


def _compare(change, doc, payload) -> list[frappe._dict]:
	"""Each field the device changed against the record as it stands, written on the change's rows."""
	writable = doc.get_permlevel_access("write")
	entries = []
	for row in change.field_changes:
		if row.table_field:
			meta = frappe.get_meta(_table(doc.meta, row.table_field).options)
			target = next(iter(doc.get(row.table_field, {"name": row.row_name})), None)
			pair = payload["rows"][row.table_field]["changed"][row.row_name][row.fieldname]
		else:
			meta, target, pair = doc.meta, doc, payload["fields"][row.fieldname]
		df = meta.get_field(row.fieldname)
		if not df or df.fieldtype in no_value_fields + table_fields:
			frappe.throw(_("{0} has no field {1} that can be changed").format(_(meta.name), row.fieldname))
		if df.permlevel not in writable:
			raise frappe.PermissionError(_("You may not change the field {0}").format(_(df.label)))

		entry = frappe._dict(row=row, target=target, value=pair.get("to"), decision=None)
		if target is None:
			# The row was removed on the server: the device's value has nowhere to go without a person
			row.conflict, row.server_value, entry.same = 1, None, False
		else:
			server = target.get(row.fieldname)
			entry.same = _same(server, pair.get("to"), df)
			row.conflict = int(not entry.same and not _same(server, pair.get("from"), df))
			row.server_value = _text(server)
		row.server_changed_by = doc.modified_by if row.conflict else None
		row.server_changed_on = doc.modified if row.conflict else None
		entries.append(entry)
	return entries


def _chosen(entries, reviewing) -> tuple[dict, dict]:
	"""The values to write: the rule's outcome per conflict, or the reviewer's choice per field."""
	values, rows = {}, {}
	for entry in entries:
		row, value = entry.row, entry.value
		if reviewing and row.resolution == "Other":
			value = row.resolved_value
		elif (reviewing and row.resolution == "Server") or entry.decision == "Server value stays":
			row.outcome = "Server kept"
			continue
		elif entry.same and not (reviewing and row.resolution):
			row.outcome = "Same"
			continue
		if entry.target is None:
			frappe.throw(
				_("Row {0} no longer exists. Keep the server's value for its fields.").format(row.row_name)
			)
		row.outcome = "Applied"
		if row.table_field:
			rows.setdefault(row.table_field, {}).setdefault("changed", {}).setdefault(row.row_name, {})[
				row.fieldname
			] = value
		else:
			values[row.fieldname] = value
	return values, rows


def _save_record(doc, values, rows, change):
	if not values and not rows:
		return
	custom = extension(doc.doctype, "apply")
	if custom:
		return custom(doc=doc, values=values, rows=rows, change=change)
	doc.update(values)
	for table_field, operations in rows.items():
		for row_name in operations.get("removed") or []:
			for row in doc.get(table_field, {"name": row_name}):
				doc.remove(row)
		for row_name, changed in (operations.get("changed") or {}).items():
			for row in doc.get(table_field, {"name": row_name}):
				row.update(changed)
		for added in operations.get("added") or []:
			doc.append(table_field, _plain(added, keep=("name",)))
	doc.save()


def _release(change):
	"""Send back to the job the changes that waited for this one."""
	waiting = frappe.get_all(
		"Offline Change", filters={"depends_on": change.name, "status": "Held"}, pluck="name"
	)
	for name in waiting:
		frappe.db.set_value(
			"Offline Change", name, {"status": "Received", "depends_on": None, "message": None}
		)
	if waiting:
		frappe.enqueue(
			"frappe_offline_changes.offline_changes.processing.process_waiting",
			names=waiting,
			enqueue_after_commit=True,
		)


def _created_offline(doctype, name) -> frappe._dict | None:
	"""The change that created this record on a device, if one did."""
	if not name:
		return None
	return frappe.db.get_value(
		"Offline Change",
		{"operation": "Create", "reference_doctype": doctype, "reference_name": name},
		["name", "status", "applied_to"],
		as_dict=True,
	)


def _point_links(meta, values) -> str | None:
	"""Point the links to records created offline at the names the server gave them.

	Returns the creation still waiting, if a link is to a record that does not exist yet."""
	for df in meta.get_link_fields():
		value = values.get(df.fieldname)
		created = _created_offline(df.options, value) if value and isinstance(value, str) else None
		if not created:
			continue
		if created.status in OPEN:
			return created.name
		values[df.fieldname] = created.applied_to or value
	return None


def _set_scope(change, name, values=None) -> tuple[str, str] | None:
	# A record that is gone tells nothing more: the scope found when the change was received is kept
	scope = scope_of(change.reference_doctype, name, values) or (
		(change.scope_doctype, change.scope_name) if change.scope_name else None
	)
	change.scope_doctype, change.scope_name = scope or (None, None)
	return scope


def _table(meta, table_field):
	df = meta.get_field(table_field)
	if not df or df.fieldtype not in table_fields:
		frappe.throw(_("{0} has no table {1}").format(_(meta.name), table_field))
	return df


def _moved(change, doc) -> bool:
	"""Whether the record changed on the server after the device read it."""
	if change.base_modified:
		return get_datetime(change.base_modified) != get_datetime(doc.modified)
	# A record the device created offline and changed before it first sent it: the device never read a version
	# from the server, so the record has moved only if someone else has saved it since
	if not _created_offline(change.reference_doctype, change.reference_name):
		frappe.throw(_("The change does not say which version of the record the device read"))
	return doc.modified_by != change.user


def _same(a, b, df) -> bool:
	return _typed(a, df) == _typed(b, df)


def _typed(value, df):
	if value is None or value == "":
		return 0 if df.fieldtype in numeric_fieldtypes else None
	value = cast_fieldtype(df.fieldtype, value, show_warning=False)
	return flt(value, 9) if isinstance(value, float) else value


def _text(value) -> str:
	if value is None:
		return ""
	return frappe.as_json(value, indent=None) if isinstance(value, dict | list) else cstr(value)


def _plain(values: dict, keep: tuple = ()) -> dict:
	"""The values a device may set: not the name, the owner, the dates or the place of a row in its record."""
	fixed = set(default_fields + child_table_fields) - set(keep)
	return {key: value for key, value in values.items() if key not in fixed}


def _hold(change, message, depends_on=None):
	change.depends_on = depends_on
	_stop(change, "Held", message)


def _stop(change, status, message=None):
	change.status, change.message = status, message


def _save(change):
	change.flags.from_module = True
	# The rule that decided, or the user who sent, may be gone by the time a reviewer acts: the row still records them
	change.flags.ignore_links = True
	# The queue is written by this module for the user whose change it is: users hold no right on the queue itself
	change.save(ignore_permissions=True)
