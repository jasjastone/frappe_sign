# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""Saved signatures moved from the User.default_signature custom field to the
Saved Signature doctype (one per email, guests included)."""

import frappe
from frappe_sign.frappe_sign.utils import file_url_to_path, save_private_file


def execute():
	if not frappe.db.exists("Custom Field", "User-default_signature"):
		return

	for user, email, file_url in frappe.db.sql(
		"select name, email, default_signature from tabUser where ifnull(default_signature, '') != ''"
	):
		email = (email or "").strip().lower()
		if not email or frappe.db.exists("Saved Signature", email):
			continue
		try:
			with open(file_url_to_path(file_url), "rb") as f:
				content = f.read()
		except FileNotFoundError:
			continue
		doc = frappe.get_doc({"doctype": "Saved Signature", "email": email}).insert(ignore_permissions=True)
		doc.db_set("signature", save_private_file("signature.png", content, "Saved Signature", doc.name, "signature"))

	frappe.delete_doc("Custom Field", "User-default_signature", force=True, ignore_permissions=True)
