# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""PDF snapshot + signature merge helpers (Section 6 of the spec)."""

import base64
import io
import os

import frappe


# The one field added to every signable doctype: what the list view shows for
# drafts. Hidden on the form (the Signers panel has the detail), filterable in
# lists, never copied to a duplicate or amendment.
SIGNATURE_STATUS_FIELD = {
	"fieldname": "signature_status",
	"label": "Signature Status",
	"fieldtype": "Select",
	"options": "\nAwaiting Signature\nSigned\nRejected",
	"read_only": 1,
	"hidden": 1,
	"no_copy": 1,
	"allow_on_submit": 1,
	"print_hide": 1,
	"in_standard_filter": 1,
}


def ensure_signature_status_field(doctype):
	"""Add signature_status to a signable doctype (idempotent)."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	if not frappe.get_meta(doctype).has_field("signature_status"):
		create_custom_fields({doctype: [SIGNATURE_STATUS_FIELD]}, ignore_validate=True)


def render_source_pdf(doctype, name, print_format=None):
	"""6.1 — render a doctype's print format to PDF bytes, exactly as the
	print view's PDF button would: same letter head, same PDF generator.

	Rendered as the document will read once submitted — the signer signs the
	real thing, not a copy marked DRAFT. Only this in-memory copy is marked
	submitted; nothing is saved, and printing the draft still says DRAFT.
	"""
	from frappe.model.docstatus import DocStatus

	doc = frappe.get_doc(doctype, name)
	if doc.meta.is_submittable and doc.docstatus.is_draft():
		doc.docstatus = DocStatus.submitted()
	return frappe.get_print(doctype, name, print_format, doc=doc, as_pdf=True)


def save_private_file(filename, content, doctype, name, fieldname):
	"""Save bytes as a private attached File; return its URL.

	Passes the bytes on the File doc itself: the legacy save_file makes File
	re-read them from disk and try text encodings, which mangles a small PNG
	that happens to decode as windows-1252.
	"""
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"attached_to_field": fieldname,
			"is_private": 1,
		}
	).insert(ignore_permissions=True)
	return f.file_url


def attach_pdf(pdf_bytes, filename, request_name, fieldname):
	"""Save PDF bytes as a private File attached to the Signature Request."""
	return save_private_file(filename, pdf_bytes, "Signature Request", request_name, fieldname)


def file_url_to_path(file_url):
	"""Disk path of a site file. Anything that resolves outside the site's own
	files folders (../, absolute paths, other URLs) is refused."""
	site_path = os.path.realpath(frappe.get_site_path())
	if (file_url or "").startswith("/private/files/"):
		base = os.path.join(site_path, "private", "files")
	elif (file_url or "").startswith("/files/"):
		base = os.path.join(site_path, "public", "files")
	else:
		frappe.throw(frappe._("Not a file on this site: {0}").format(file_url), frappe.PermissionError)
	path = os.path.realpath(os.path.join(base, file_url.split("/files/", 1)[1]))
	if not path.startswith(base + os.sep):
		frappe.throw(frappe._("Not a file on this site: {0}").format(file_url), frappe.PermissionError)
	return path


def check_boxes_fit(pdf_bytes, signers):
	"""Every box must sit on a page the PDF actually has — checked when a request
	is sent, so a bad box can't turn into a signing error later."""
	import fitz

	doc = fitz.open(stream=pdf_bytes, filetype="pdf")
	try:
		for s in signers:
			for b in s["sign_boxes"]:
				if b["page"] >= len(doc):
					frappe.throw(
						frappe._("A signature box for {0} is on page {1}, but the document has only {2}.").format(
							s.get("signer_name"), b["page"] + 1, len(doc)
						)
					)
				page = doc[b["page"]].rect
				if b["x"] + b["w"] > page.width + 1 or b["y"] + b["h"] > page.height + 1:
					frappe.throw(frappe._("A signature box for {0} runs off the page.").format(s.get("signer_name")))
	finally:
		doc.close()


def check_readable_pdf(file_url):
	"""An uploaded PDF the user can actually read — never an arbitrary path.
	Returns the File record's name."""
	file = file_url and frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file or not file_url.lower().endswith(".pdf"):
		frappe.throw(frappe._("Only PDF files can be used as the document to sign."))
	if not frappe.has_permission("File", "read", file):
		raise frappe.PermissionError
	return file


def merge_pdf_files(file_urls):
	"""Join PDFs in the given order; returns the bytes."""
	import fitz

	out = fitz.open()
	try:
		for url in file_urls:
			try:
				src = fitz.open(file_url_to_path(url))
			except Exception:
				frappe.throw(frappe._("{0} could not be read as a PDF.").format(url.rsplit("/", 1)[-1]))
			with src:
				out.insert_pdf(src)
		return out.tobytes()
	finally:
		out.close()


def decode_image(image_base64):
	"""Turn the transient base64 payload from the API call into raw bytes (D9)."""
	if "," in image_base64:
		image_base64 = image_base64.split(",", 1)[1]
	return base64.b64decode(image_base64)


def max_signature_px():
	"""Longest side of a stored signature (Signature Settings). A box is a few
	inches wide; a phone photo at full size made a signed PDF tens of MB.
	The browser gets it with the signing context, so this is the one source."""
	return frappe.utils.cint(frappe.db.get_single_value("Signature Settings", "max_signature_px")) or 1000


def shrink_signature(image_bytes):
	"""The signature as a PNG no larger than max_signature_px() on its longest side.
	Done here too, not only in the browser: the API takes whatever is posted."""
	import fitz

	try:
		pix = fitz.Pixmap(image_bytes)
	except Exception:
		frappe.throw(frappe._("The signature must be an image."))
	scale = max_signature_px() / max(pix.width, pix.height)
	if scale >= 1:
		return image_bytes  # already small: keep it byte for byte (the saved one is compared as-is)
	return fitz.Pixmap(pix, max(1, round(pix.width * scale)), max(1, round(pix.height * scale)), None).tobytes("png")


def merge_signature(current_pdf_url, signature_image_bytes, signer, signed_on):
	"""6.3 — stamp the signer's boxes: the signature image into each signature box,
	their name / the signing date as text into name and date boxes. Nothing else:
	who signed, when and from where are kept on the signer row (signed_on,
	signed_ip), not printed on the document.

	`signature_image_bytes` comes straight from the API payload and is never
	read from storage (D9). Returns the new PDF as bytes.
	"""
	import fitz

	texts = {"name": signer.signer_name, "date": frappe.utils.formatdate(signed_on)}
	doc = fitz.open(file_url_to_path(current_pdf_url))
	try:
		# The same signature goes into every box this signer was given — stored
		# once, every other box points at that copy.
		xref = 0
		for box in frappe.parse_json(signer.sign_boxes) or []:
			rect = fitz.Rect(box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
			page = doc[int(box["page"])]
			kind = box.get("type") or "signature"
			if kind != "signature":
				stamp_text(page, rect, texts[kind])
			elif xref:
				page.insert_image(rect, xref=xref)
			else:
				xref = page.insert_image(rect, stream=signature_image_bytes)
		out = io.BytesIO()
		# PyMuPDF stores an inserted image's pixels uncompressed unless told to
		# deflate (a 1800x1200 signature was ~7 MB). garbage=3 drops leftovers.
		doc.save(out, garbage=3, deflate=True)
		return out.getvalue()
	finally:
		doc.close()


def stamp_text(page, rect, text):
	"""One line of text, as large as fits the box, vertically centred."""
	import fitz

	pad = 2
	size = min(rect.height * 0.7, (rect.width - 2 * pad) / max(fitz.get_text_length(text, fontsize=1), 1))
	page.insert_text((rect.x0 + pad, rect.y0 + (rect.height + size * 0.7) / 2), text, fontsize=size)
