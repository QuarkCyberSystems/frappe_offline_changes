from frappe.model.document import Document


class OfflineChangeDocType(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allow_create: DF.Check
		allow_delete: DF.Check
		allow_update: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		reference_doctype: DF.Link
		replaced_by_field: DF.Data | None
		scope_field: DF.Data | None
	# end: auto-generated types

	pass
