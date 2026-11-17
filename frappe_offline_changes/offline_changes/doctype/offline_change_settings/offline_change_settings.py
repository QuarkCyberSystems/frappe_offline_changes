"""Which DocTypes a device may change offline, and how the queue is kept."""

import frappe
from frappe import _
from frappe.model.document import Document


class OfflineChangeSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from frappe_offline_changes.offline_changes.doctype.offline_change_doctype.offline_change_doctype import (
			OfflineChangeDocType,
		)

		doctypes: DF.Table[OfflineChangeDocType]
		enabled: DF.Check
		keep_values_days: DF.Int
		max_batch_size: DF.Int
		reviewers_see_unscoped: DF.Check
	# end: auto-generated types

	def validate(self):
		seen = set()
		for row in self.doctypes:
			meta = frappe.get_meta(row.reference_doctype)
			if meta.istable or meta.issingle or meta.is_virtual:
				frappe.throw(
					_(
						"Row {0}: {1} cannot be changed offline. Choose a DocType with records of its own"
					).format(row.idx, _(row.reference_doctype))
				)
			if row.reference_doctype in seen:
				frappe.throw(_("Row {0}: {1} is listed twice").format(row.idx, _(row.reference_doctype)))
			seen.add(row.reference_doctype)
			self.validate_named_field(row, meta, "scope_field")
			self.validate_named_field(row, meta, "replaced_by_field", to=row.reference_doctype)

	def validate_named_field(self, row, meta, setting, to=None):
		"""A field named here is a link of the DocType; the replaced-by field, a link to the DocType itself."""
		fieldname = row.get(setting)
		if not fieldname:
			return
		df = meta.get_field(fieldname)
		label = _(row.meta.get_label(setting))
		if not df or df.fieldtype != "Link" or (to and df.options != to):
			frappe.throw(
				_("Row {0}: {1} is not a link field of {2} that can be the {3}").format(
					row.idx, fieldname, _(row.reference_doctype), label
				)
			)

	def allows(self, doctype: str, operation: str) -> bool:
		"""Whether a device may send this operation (Create, Update, Delete) for this DocType."""
		row = next((row for row in self.doctypes if row.reference_doctype == doctype), None)
		return bool(self.enabled and row and row.get(f"allow_{operation.lower()}"))
