# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""Role that gates who sees the Sign app (workspace, dashboard, form buttons)."""

import frappe


def execute():
	if not frappe.db.exists("Role", "Sign User"):
		frappe.get_doc({"doctype": "Role", "role_name": "Sign User", "desk_access": 1}).insert(
			ignore_permissions=True
		)
