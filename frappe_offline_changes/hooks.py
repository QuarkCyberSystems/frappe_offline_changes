app_name = "frappe_offline_changes"
app_title = "Offline Changes"
app_publisher = "Quark Cyber Systems"
app_description = "Receives changes captured offline, applies them and holds conflicts for review"
app_email = "vivek@quarkcs.com"

export_python_type_annotations = True

after_install = "frappe_offline_changes.install.after_install"

# A reviewer handles the changes of their scopes only. Which scopes those are, and the rest of what the app
# owning a DocType tells this one, is asked through the hooks described in frappe_offline_changes.utils.extensions
has_permission = {
	"Offline Change": "frappe_offline_changes.offline_changes.doctype.offline_change.offline_change.has_permission"
}
permission_query_conditions = {
	"Offline Change": "frappe_offline_changes.offline_changes.doctype.offline_change.offline_change.query_conditions"
}

scheduler_events = {
	"daily": [
		"frappe_offline_changes.offline_changes.doctype.offline_change.offline_change.remove_old_values"
	]
}
