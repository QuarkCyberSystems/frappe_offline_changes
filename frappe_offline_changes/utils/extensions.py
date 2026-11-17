"""What the app that owns a DocType tells this one, through hooks.

This app knows no DocType but its own. An app whose records are changed offline answers, in its `hooks.py`:

        offline_changes = {
                "Person": {  # or "*" for every DocType
                        "scope": "app.module.scope",  # (doctype, name, values) -> (scope_doctype, scope_name) | None
                        "replaced_by": "app.module.replaced_by",  # (doctype, name) -> name | None
                        "apply": "app.module.apply",  # (doc, values, rows, change): saves the change itself
                        "after_create": "app.module.after_create",  # (doc, change)
                }
        }
        offline_change_reviewer_scopes = "app.module.scopes"  # (user) -> [(scope_doctype, scope_name)]

The scope is the business unit a record belongs to: it narrows a conflict rule, and it decides which
reviewers see a change.

Where the answer is a field of the record, no code is needed: Offline Change Settings names, per DocType, the
link field that holds the scope and the one that holds the record's replacement, and Offline Review Scope
lists who reviews which scope. A hook, where an app registers one, is asked first. A DocType with neither has
no scope, is never replaced, and is saved through the document API.
"""

import frappe

ANY = "*"
# A record merged into another that was itself merged: followed this far, then left as found
REPLACEMENTS_FOLLOWED = 10


def extension(doctype: str, kind: str):
	"""The function an app registered for this DocType, the last installed app first; None when no app did."""
	hooks = frappe.get_hooks("offline_changes") or {}
	for key in (doctype, ANY):
		paths = (hooks.get(key) or {}).get(kind)
		if paths:
			return frappe.get_attr(paths[-1])
	return None


def scope_of(
	doctype: str, name: str | None, values: dict | None = None, hint: str | None = None
) -> tuple[str, str] | None:
	"""The business unit of a record.

	Read from the record. For one about to be created, from its values. For one that no longer exists, from
	what Frappe kept of it when it was deleted, and failing that from what the device believed (`hint`), which
	is taken only for a scope the sender may read."""
	function = extension(doctype, "scope")
	if function:
		found = function(doctype=doctype, name=name, values=values)
		return (found[0], found[1]) if found and found[0] and found[1] else None
	field = _named_field(doctype, "scope_field")
	if not field:
		return None
	scope_doctype = frappe.get_meta(doctype).get_field(field).options
	if name and frappe.db.exists(doctype, name):
		scope = frappe.db.get_value(doctype, name, field)
	elif values:
		scope = values.get(field)
	else:
		scope = _deleted_value(doctype, name, field) or _trusted(scope_doctype, hint)
	return (scope_doctype, scope) if scope else None


def replaced_by(doctype: str, name: str) -> str | None:
	"""The record that took this one's place on the server (a duplicate merged into another), if any."""
	function = extension(doctype, "replaced_by")
	if function:
		return function(doctype=doctype, name=name) or None
	field = _named_field(doctype, "replaced_by_field")
	if not field:
		return None
	last, seen = None, {name}
	for _hop in range(REPLACEMENTS_FOLLOWED):
		following = frappe.db.get_value(doctype, last or name, field)
		if not following or following in seen:
			break
		last = following
		seen.add(following)
	return last


def reviewer_scopes(user: str) -> list[tuple[str, str]]:
	"""The scopes whose changes this reviewer handles: as an app answers, else as Offline Review Scope lists."""
	paths = frappe.get_hooks("offline_change_reviewer_scopes")
	if not paths:
		# The list is read for the permission check itself: the reviewer holds no right on it
		listed = frappe.get_all(
			"Offline Review Scope",
			filters={"user": user},
			fields=["scope_doctype", "scope_name"],
			as_list=True,
		)
		return [(scope_doctype, scope_name) for scope_doctype, scope_name in listed]
	scopes = []
	for path in paths:
		scopes.extend(
			(scope_doctype, scope_name)
			for scope_doctype, scope_name in frappe.get_attr(path)(user=user) or []
		)
	return scopes


def _named_field(doctype: str, setting: str) -> str | None:
	"""The field Offline Change Settings names for this DocType."""
	return frappe.db.get_value(
		"Offline Change DocType",
		{"parenttype": "Offline Change Settings", "reference_doctype": doctype},
		setting,
	)


def _deleted_value(doctype: str, name: str | None, field: str):
	data = name and frappe.db.get_value(
		"Deleted Document",
		{"deleted_doctype": doctype, "deleted_name": name},
		"data",
		order_by="creation desc",
	)
	return frappe.parse_json(data).get(field) if data else None


def _trusted(scope_doctype: str, hint: str | None) -> str | None:
	if not hint or not isinstance(hint, str) or not frappe.db.exists(scope_doctype, hint):
		return None
	return hint if frappe.has_permission(scope_doctype, "read", hint) else None
