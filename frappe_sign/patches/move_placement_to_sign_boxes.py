# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""A signer can now sign in several places: the single sign_page/x/y/width/height
placement becomes a one-item sign_boxes list. Frappe keeps removed columns, so the
old values are still there to read."""

import frappe


def execute():
	columns = frappe.db.get_table_columns("Signature Request Signer")
	if "sign_width" not in columns:
		return

	rows = frappe.db.sql(
		"""select name, sign_page, sign_x, sign_y, sign_width, sign_height
		from `tabSignature Request Signer`
		where ifnull(sign_boxes, '') = '' and ifnull(sign_width, 0) > 0""",
		as_dict=True,
	)
	for r in rows:
		box = {"page": int(r.sign_page or 0), "x": r.sign_x, "y": r.sign_y, "w": r.sign_width, "h": r.sign_height}
		frappe.db.set_value(
			"Signature Request Signer", r.name, "sign_boxes", frappe.as_json([box]), update_modified=False
		)
