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
        offline_change_reviewer_scopes = "app.module.scopes"  # (user) -> [(scope_doctype, scope_name)] | None

The scope is the business unit a record belongs to: it narrows a conflict rule, and it decides which
reviewers see a change. A DocType with no answer has no scope, is never replaced, and is saved through the
document API.
"""

import frappe

ANY = "*"


def extension(doctype: str, kind: str):
	"""The function an app registered for this DocType, the last installed app first; None when no app did."""
	hooks = frappe.get_hooks("offline_changes") or {}
	for key in (doctype, ANY):
		paths = (hooks.get(key) or {}).get(kind)
		if paths:
			return frappe.get_attr(paths[-1])
	return None


def scope_of(doctype: str, name: str | None, values: dict | None = None) -> tuple[str, str] | None:
	"""The business unit of a record; of the values of one about to be created when it has no name yet."""
	function = extension(doctype, "scope")
	found = function(doctype=doctype, name=name, values=values) if function else None
	return (found[0], found[1]) if found and found[0] and found[1] else None


def replaced_by(doctype: str, name: str) -> str | None:
	"""The record that took this one's place on the server (a duplicate merged into another), if any."""
	function = extension(doctype, "replaced_by")
	return (function(doctype=doctype, name=name) or None) if function else None


def reviewer_scopes(user: str) -> list[tuple[str, str]] | None:
	"""The scopes whose changes this reviewer handles; None when no app limits reviewers, or lifts the limit."""
	paths = frappe.get_hooks("offline_change_reviewer_scopes")
	if not paths:
		return None
	scopes = []
	for path in paths:
		found = frappe.get_attr(path)(user=user)
		if found is None:
			return None
		scopes.extend((scope_doctype, scope_name) for scope_doctype, scope_name in found)
	return scopes
