app_name = "frappe_offline_changes"
app_title = "Offline Changes"
app_publisher = "Quark Cyber Systems"
app_description = "Receives changes captured offline, applies them and holds conflicts for review"
app_email = "vivek@quarkcs.com"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "frappe_offline_changes",
# 		"logo": "/assets/frappe_offline_changes/logo.png",
# 		"title": "Offline Changes",
# 		"route": "/frappe_offline_changes",
# 		"has_permission": "frappe_offline_changes.api.permission.has_app_permission",
# 	}
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `frappe_offline_changes/dock/frappe_offline_changes/frappe_offline_changes.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_offline_changes/css/frappe_offline_changes.css"
# app_include_js = "/assets/frappe_offline_changes/js/frappe_offline_changes.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_offline_changes/css/frappe_offline_changes.css"
# web_include_js = "/assets/frappe_offline_changes/js/frappe_offline_changes.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_offline_changes/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_kanban_js = {"doctype" : "public/js/doctype_kanban.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "frappe_offline_changes/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_offline_changes.utils.jinja_methods",
# 	"filters": "frappe_offline_changes.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "frappe_offline_changes.install.before_install"
# after_install = "frappe_offline_changes.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "frappe_offline_changes.uninstall.before_uninstall"
# after_uninstall = "frappe_offline_changes.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_offline_changes.utils.before_app_install"
# after_app_install = "frappe_offline_changes.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_offline_changes.utils.before_app_uninstall"
# after_app_uninstall = "frappe_offline_changes.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "frappe_offline_changes.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "frappe_offline_changes.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_offline_changes.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["frappe_offline_changes.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"frappe_offline_changes.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_offline_changes.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_offline_changes.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_offline_changes.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_offline_changes.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_offline_changes.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "frappe_offline_changes.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_offline_changes.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_offline_changes.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_offline_changes.utils.before_request"]
# after_request = ["frappe_offline_changes.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_offline_changes.utils.before_job"]
# after_job = ["frappe_offline_changes.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"frappe_offline_changes.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

