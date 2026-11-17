from frappe.model.document import Document


class OfflineChangeField(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		base_value: DF.LongText | None
		conflict: DF.Check
		device_value: DF.LongText | None
		fieldname: DF.Data
		label: DF.Data | None
		outcome: DF.Literal["", "Applied", "Same", "Server kept", "Held", "Refused"]
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		resolution: DF.Literal["", "Device", "Server", "Other"]
		resolved_value: DF.LongText | None
		row_name: DF.Data | None
		rule: DF.Link | None
		server_changed_by: DF.Link | None
		server_changed_on: DF.Datetime | None
		server_value: DF.LongText | None
		table_field: DF.Data | None
	# end: auto-generated types

	pass
