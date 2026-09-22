# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""Give every existing signable doctype its signature_status field, filled in
from each record's latest request."""

import frappe

from frappe_sign.frappe_sign.utils import ensure_signature_status_field


def execute():
	for doctype in frappe.get_all("Signable Document Type", pluck="document_type"):
		ensure_signature_status_field(doctype)

	latest = frappe.db.sql(
		"""select r.reference_doctype, r.reference_name, r.status
		from `tabSignature Request` r
		join (
			select reference_doctype, reference_name, max(creation) creation
			from `tabSignature Request`
			where ifnull(reference_name, '') != ''
			group by reference_doctype, reference_name
		) m on m.reference_doctype = r.reference_doctype
			and m.reference_name = r.reference_name and m.creation = r.creation""",
		as_dict=True,
	)
	for r in latest:
		if frappe.get_meta(r.reference_doctype).has_field("signature_status") and frappe.db.exists(
			r.reference_doctype, r.reference_name
		):
			status = {"Draft": "Awaiting Signature", "Withdrawn": ""}.get(r.status, r.status)
			frappe.db.set_value(
				r.reference_doctype, r.reference_name, "signature_status", status, update_modified=False
			)
