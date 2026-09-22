app_name = "frappe_sign"
app_title = "Sign"
app_publisher = "jasjastone"
app_description = "Embedded e-signature system for ERPNext"
app_email = "jasjastone@gmail.com"
app_license = "mit"

# Apps screen
# -----------
add_to_apps_screen = [
	{
		"name": app_name,
		"logo": "/assets/frappe_sign/images/sign.svg",
		"title": app_title,
		"route": "/app/e-signature",
	}
]

# Includes in <head>
# ------------------
# Bundles get a content hash per build, so browsers never run a stale copy.
app_include_js = "frappe_sign.bundle.js"
app_include_css = "sign.bundle.css"

# Signable types ride along in boot so forms can hide Submit before first paint.
boot_session = "frappe_sign.frappe_sign.api.boot_session"

# Document Events
# ---------------
# Signable records are locked while out for signature, and can't be submitted
# until signed (per Signable Document Type).
scheduler_events = {"cron": {"*/15 * * * *": ["frappe_sign.frappe_sign.api.send_reminders"]}}

doc_events = {
	"*": {
		"validate": "frappe_sign.frappe_sign.api.check_not_out_for_signature",
		"before_submit": "frappe_sign.frappe_sign.api.check_signed_before_submit",
	}
}

# Website
# -------
website_route_rules = [
	{"from_route": "/sign-document", "to_route": "sign_document"},
]
