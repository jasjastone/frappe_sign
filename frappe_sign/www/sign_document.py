# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""7.4 — the /sign-document?key=<token> page, used by every signer type."""

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.key = frappe.form_dict.get("key") or ""
	return context
