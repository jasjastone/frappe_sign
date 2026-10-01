# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SignatureSettings(Document):
	def validate(self):
		if self.max_signature_px and self.max_signature_px < 200:
			frappe.throw(_("Max Signature Size must be at least 200 px, or a signature turns blurry."))
