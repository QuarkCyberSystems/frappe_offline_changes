"""The rules that decide what becomes of a change captured offline.

A rule gives the outcome of one situation. It may be narrowed to a DocType, to a field of it, and to a scope
(the business unit a record belongs to, as the app owning the DocType defines it). The narrowest rule that
fits is the one applied: a rule for the record's scope before a rule for every scope, then a rule for the
field before a rule for the DocType, before a rule for everything.

Three outcomes are not rules, and so cannot be changed here: a change the user may no longer make is
refused, a change already received is ignored, and a deletion made offline of a record changed since is held
for review.
"""

import frappe
from frappe import _
from frappe.model import no_value_fields, table_fields
from frappe.model.document import Document

HOLD = "Hold for review"
OUTCOMES = {
	"Different fields changed": ("Merge", HOLD),
	"Same field changed": ("Last to arrive wins", "Server value stays", HOLD),
	"Changed on device, deleted on server": ("Deletion stands", HOLD),
	"Record replaced on server": ("Apply to the replacement", HOLD),
}


class ConflictRule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		description: DF.SmallText | None
		enabled: DF.Check
		fieldname: DF.Data | None
		outcome: DF.Literal[
			"Merge",
			"Last to arrive wins",
			"Server value stays",
			"Deletion stands",
			"Apply to the replacement",
			"Hold for review",
		]
		reference_doctype: DF.Link | None
		scope_doctype: DF.Link | None
		scope_name: DF.DynamicLink | None
		situation: DF.Literal[
			"Different fields changed",
			"Same field changed",
			"Changed on device, deleted on server",
			"Record replaced on server",
		]
	# end: auto-generated types

	def validate(self):
		if self.outcome not in OUTCOMES[self.situation]:
			frappe.throw(
				_("{0} is not an outcome of the situation {1}. Choose one of: {2}").format(
					_(self.outcome), _(self.situation), ", ".join(_(o) for o in OUTCOMES[self.situation])
				)
			)
		if not self.scope_doctype:
			self.scope_name = None
		elif not self.scope_name:
			frappe.throw(_("Name the scope, or leave the scope type empty"))
		if not self.reference_doctype:
			self.fieldname = None
		if self.fieldname:
			self.validate_field()
		self.validate_unique()

	def validate_field(self):
		if self.situation != "Same field changed":
			frappe.throw(
				_("Only a rule for the situation {0} can name a field").format(_("Same field changed"))
			)
		if self.fieldname not in fieldnames(self.reference_doctype):
			frappe.throw(
				_("{0} has no field {1}, in the record or in its tables").format(
					_(self.reference_doctype), self.fieldname
				)
			)

	def validate_unique(self):
		if not self.enabled:
			return
		other = frappe.db.get_value(
			"Conflict Rule",
			{
				"name": ("!=", self.name),
				"enabled": 1,
				"situation": self.situation,
				"reference_doctype": self.reference_doctype or ("is", "not set"),
				"fieldname": self.fieldname or ("is", "not set"),
				"scope_doctype": self.scope_doctype or ("is", "not set"),
				"scope_name": self.scope_name or ("is", "not set"),
			},
		)
		if other:
			frappe.throw(_("Rule {0} already decides this situation for the same records").format(other))


def fieldnames(doctype: str) -> set[str]:
	"""The fields of a DocType that hold a value, with those of its child tables."""
	meta = frappe.get_meta(doctype)
	names = {df.fieldname for df in meta.fields if df.fieldtype not in no_value_fields + table_fields}
	for table in meta.get_table_fields():
		names |= {
			df.fieldname
			for df in frappe.get_meta(table.options).fields
			if df.fieldtype not in no_value_fields
		}
	return names


def find_rule(
	situation: str, doctype: str, fieldname: str | None = None, scope: tuple[str, str] | None = None
) -> frappe._dict | None:
	"""The narrowest enabled rule for this situation; None when no rule fits, and the change is then held."""
	fits = []
	for rule in frappe.get_all(
		"Conflict Rule",
		filters={"situation": situation, "enabled": 1},
		fields=["name", "outcome", "reference_doctype", "fieldname", "scope_doctype", "scope_name"],
	):
		if rule.reference_doctype and rule.reference_doctype != doctype:
			continue
		if rule.fieldname and rule.fieldname != fieldname:
			continue
		if rule.scope_name and (rule.scope_doctype, rule.scope_name) != scope:
			continue
		fits.append(((bool(rule.scope_name), bool(rule.fieldname), bool(rule.reference_doctype)), rule))
	return max(fits, key=lambda fit: fit[0])[1] if fits else None
