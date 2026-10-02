# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Set only by the app: from the form, a user can start a Draft (title + PDF),
# nothing more. Sending, signing, declining and withdrawing go through api.py.
SYSTEM_FIELDS = (
	"reference_doctype",
	"reference_name",
	"created_by_user",
	"signed_pdf",
	"rejected_by",
	"rejection_reason",
	"sign_in_order",
)


class SignatureRequest(Document):
	def validate(self):
		if self.flags.from_sign_api:
			return

		before = None if self.is_new() else self.get_doc_before_save()
		if self.status != "Draft" or (before and before.status != "Draft"):
			frappe.throw(_("A signature request can only be changed from its buttons once it has been sent."))
		if self.signers:
			frappe.throw(_("Add signers with the Request Signature button."))
		for field in SYSTEM_FIELDS:
			if (self.get(field) or None) != ((before.get(field) if before else None) or None):
				frappe.throw(_("{0} is set by the system.").format(_(self.meta.get_label(field))))

		if self.is_new():
			self.created_by_user = frappe.session.user
		if not before or before.source_pdf != self.source_pdf:
			self.validate_source_pdf()
		if not self.title and self.source_pdf:
			self.title = self.source_pdf.rsplit("/", 1)[-1]

	def validate_source_pdf(self):
		from frappe_sign.frappe_sign.utils import check_readable_pdf

		if self.source_pdf:
			check_readable_pdf(self.source_pdf)


# Who sees what. The role rows grant Sign User / Sign Manager every request;
# these hooks narrow a Sign User down (a hook can deny, never grant).
OVERSEERS = ("Sign Manager", "System Manager")


def _oversees(user):
	return user == "Administrator" or bool(set(OVERSEERS) & set(frappe.get_roles(user)))


def has_permission(doc, ptype=None, user=None, debug=False):
	"""A Sign User: their own requests, plus — read-only — a request on any record
	they can read, so a colleague on the same Purchase Order sees how it was
	signed. A standalone (uploaded PDF) request stays its creator's."""
	user = user or frappe.session.user
	if _oversees(user) or doc.is_new() or doc.owner == user:
		return True
	return bool(
		ptype in ("read", "print")
		and doc.reference_doctype
		and doc.reference_name
		and frappe.has_permission(doc.reference_doctype, "read", doc.reference_name, user=user)
	)


def get_permission_query_conditions(user=None):
	"""The list: a Sign User's own requests only. Record readability can't be
	checked per row in SQL; the record's Signers panel links the rest."""
	user = user or frappe.session.user
	if _oversees(user):
		return ""
	return f"`tabSignature Request`.`owner` = {frappe.db.escape(user)}"
