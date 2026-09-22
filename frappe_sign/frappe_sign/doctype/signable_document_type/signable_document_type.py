# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SignableDocumentType(Document):
	# These rows travel to every form in boot (api.boot_session), which Frappe
	# caches per user — drop it so a change reaches everyone on their next load.
	def on_update(self):
		from frappe_sign.frappe_sign.utils import ensure_signature_status_field

		ensure_signature_status_field(self.document_type)
		frappe.cache.delete_key("bootinfo")

	def on_trash(self):
		frappe.cache.delete_key("bootinfo")
