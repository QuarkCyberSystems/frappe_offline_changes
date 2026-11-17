import frappe

# The rules a site starts with: merge what does not collide, the last change to arrive wins a collision, and a
# person decides what to do with a change to a record deleted meanwhile. An administrator changes them.
RULES = (
	("Different fields changed", "Merge"),
	("Same field changed", "Last to arrive wins"),
	("Changed on device, deleted on server", "Hold for review"),
	("Record replaced on server", "Apply to the replacement"),
)


def after_install():
	add_rules()


def add_rules():
	"""Give each situation its rule for every record, where the site has none yet."""
	for situation, outcome in RULES:
		general = {
			"situation": situation,
			"reference_doctype": ("is", "not set"),
			"scope_name": ("is", "not set"),
		}
		if not frappe.db.exists("Conflict Rule", general):
			frappe.get_doc({"doctype": "Conflict Rule", "situation": situation, "outcome": outcome}).insert()
