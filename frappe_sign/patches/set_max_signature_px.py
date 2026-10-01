# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""Max Signature Size arrived after Signature Settings existed: show the value
in use (1000) on the settings page instead of a blank field."""

import frappe


def execute():
	if not frappe.db.get_single_value("Signature Settings", "max_signature_px"):
		frappe.db.set_single_value("Signature Settings", "max_signature_px", 1000)
