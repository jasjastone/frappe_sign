# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""Signed PDFs used to carry "Signed by <name> on <date> (IP: <ip>)" under each
signature. Only the signature belongs on the document — who, when and where are
on the signer row — so take that text out of the PDFs already signed."""

import hashlib

import frappe

from frappe_sign.frappe_sign.utils import file_url_to_path


def execute():
	for req in frappe.get_all("Signature Request", {"signed_pdf": ["is", "set"]}, ["name", "signed_pdf"]):
		signers = frappe.get_all(
			"Signature Request Signer",
			{"parent": req.name, "parenttype": "Signature Request", "signed_on": ["is", "set"]},
			["signer_name", "signed_on", "signed_ip"],
		)
		# Exactly what merge_signature used to print, so nothing else on the page matches.
		lines = [
			f"Signed by {s.signer_name} on {s.signed_on.strftime('%Y-%m-%d %H:%M')} (IP: {s.signed_ip})"
			for s in signers
		]
		try:
			path = file_url_to_path(req.signed_pdf)
			with open(path, "rb") as f:
				cleaned = strip_lines(f.read(), lines)
			if cleaned is None:
				continue
			with open(path, "wb") as f:
				f.write(cleaned)
			frappe.db.set_value(
				"File",
				{"file_url": req.signed_pdf},
				{"content_hash": hashlib.md5(cleaned).hexdigest(), "file_size": len(cleaned)},
				update_modified=False,
			)
		except Exception:
			# One unreadable file costs that file, never the migrate.
			frappe.log_error(title=f"Sign: couldn't remove audit line from {req.name}")


def strip_lines(pdf_bytes, lines):
	"""Remove each of `lines` wherever it is printed; images and drawings are left
	untouched. Returns the new PDF bytes, or None when none of the lines is there."""
	import fitz

	doc = fitz.open(stream=pdf_bytes, filetype="pdf")
	try:
		found = False
		for page in doc:
			hits = [r for line in lines for r in page.search_for(line)]
			for r in hits:
				# Trimmed a point top and bottom so text touching the line isn't taken too.
				page.add_redact_annot(fitz.Rect(r.x0, r.y0 + 1, r.x1, r.y1 - 1), fill=False)
			if hits:
				found = True
				page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
		return doc.tobytes(garbage=3, deflate=True) if found else None
	finally:
		doc.close()
