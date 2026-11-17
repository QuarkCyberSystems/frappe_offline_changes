"""Who reviews the changes of which scope, where no app answers that question itself.

A reviewer sees the changes of the scopes listed here for them, and no other change that has a scope. An app
that already knows who is responsible for a business unit answers through the `offline_change_reviewer_scopes`
hook instead (frappe_offline_changes.utils.extensions), and this list is then not read.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class OfflineReviewScope(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		scope_doctype: DF.Link
		scope_name: DF.DynamicLink
		user: DF.Link
	# end: auto-generated types

	def validate(self):
		same = {
			"name": ("!=", self.name),
			"user": self.user,
			"scope_doctype": self.scope_doctype,
			"scope_name": self.scope_name,
		}
		if frappe.db.exists("Offline Review Scope", same):
			frappe.throw(_("{0} already reviews {1}").format(self.user, self.scope_name))
