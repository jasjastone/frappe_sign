# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""All whitelisted methods for the Sign app (Section 5 of the spec)."""

import base64

import frappe
from frappe import _
from frappe.utils import add_days, cint, escape_html, flt, get_url, now_datetime

from frappe_sign.frappe_sign.utils import (
	attach_pdf,
	check_boxes_fit,
	check_readable_pdf,
	decode_image,
	file_url_to_path,
	merge_pdf_files,
	merge_signature,
	render_source_pdf,
	save_private_file,
)

SIGNER_TYPES = ("User", "Employee", "Customer", "Supplier", "Email")


# ---------------------------------------------------------------------------
# 5.1 create_signature_request
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_signature_request(reference_doctype, reference_name, signers, sign_in_order=0):
	"""Send a signable record out for signature.

	A PDF with no record behind it (a letter, an office document) starts as a
	Draft Signature Request with the file attached, and is sent from its form
	with update_signature_request.
	"""
	if not frappe.has_permission(reference_doctype, "write", reference_name):
		raise frappe.PermissionError(
			_("You are not permitted to request a signature on {0} {1}").format(reference_doctype, reference_name)
		)
	config = _get_signable_config(reference_doctype)
	signers = _clean_signers(signers, config)
	pdf_bytes = render_source_pdf(reference_doctype, reference_name, config.default_print_format)
	check_boxes_fit(pdf_bytes, signers)

	request = frappe.new_doc("Signature Request")
	request.reference_doctype = reference_doctype
	request.reference_name = reference_name
	request.created_by_user = frappe.session.user
	request.status = "Awaiting Signature"
	request.title = _("{0} — Signature Request").format(reference_name)
	request.sign_in_order = cint(sign_in_order)
	for s in signers:
		request.append("signers", _new_signer_row(s))

	# The snapshot can only be attached once the request has a name, so the
	# mandatory check on source_pdf is deferred to just after insert.
	request.flags.ignore_mandatory = True
	request.flags.from_sign_api = True
	request.insert(ignore_permissions=True)
	request.db_set(
		"source_pdf",
		attach_pdf(pdf_bytes, f"{reference_name}.pdf", request.name, "source_pdf"),
		update_modified=False,
	)

	_set_reference_status(request)
	_notify_turn(request)

	return {"name": request.name, "title": request.title}


def _signer_values(s):
	"""The editable part of a signer row, from a validated payload."""
	return {
		"signer_type": s.get("signer_type"),
		"signer_reference": s.get("signer_reference") or None,
		"signer_name": s.get("signer_name"),
		"signer_email": s.get("signer_email"),
		"sign_boxes": frappe.as_json(s["sign_boxes"]),
	}


def _new_signer_row(s):
	"""A fresh Pending signer with its own link. The link's validity starts when
	it is mailed (_notify_turn), so a signer at the end of an order doesn't run
	out of time waiting for the others."""
	return {**_signer_values(s), "status": "Pending", "access_token": frappe.generate_hash(length=32)}


# ---------------------------------------------------------------------------
# Signing order and reminders
# ---------------------------------------------------------------------------


def _is_turn(request, signer):
	"""Everyone may sign at once, unless the request is in order: then only the
	first signer still pending, top to bottom."""
	if signer.status != "Pending":
		return False
	if not request.sign_in_order:
		return True
	return next(s for s in request.signers if s.status == "Pending").name == signer.name


def _notify_turn(request):
	"""Invite everyone whose turn it is and who hasn't been invited yet.

	Safe to call after any change — sending, updating, each signature — since an
	invited signer is never mailed twice. Their link's validity starts now.
	"""
	validity = cint(frappe.db.get_single_value("Signature Settings", "token_validity_days")) or 14
	for signer in request.signers:
		if signer.invited_on or not _is_turn(request, signer):
			continue
		signer.db_set(
			{"invited_on": now_datetime(), "token_expiry": add_days(now_datetime(), validity)},
			update_modified=False,
		)
		_email_request_created(request, signer)


# A pending signer whose turn it is, in SQL (s: the signer row, r: its request).
IN_TURN_SQL = """s.status = 'Pending' and r.status = 'Awaiting Signature'
	and (r.sign_in_order = 0 or not exists (
		select 1 from `tabSignature Request Signer` e
		where e.parent = r.name and e.parenttype = 'Signature Request'
			and e.status = 'Pending' and e.idx < s.idx))"""


@frappe.whitelist()
def send_reminder(request):
	"""Remind whoever the request is waiting on, now."""
	req = frappe.get_doc("Signature Request", request)
	_check_can_manage(req)
	if req.status != "Awaiting Signature":
		frappe.throw(_("{0} isn't waiting for anyone.").format(req.name))
	waiting = [s for s in req.signers if _is_turn(req, s)]
	for signer in waiting:
		_remind(req, signer)
	return [s.signer_name for s in waiting]


# When reminders go out, in hours after a signer is invited (the document was
# sent, or their turn came). Nothing after the last one.
REMINDER_HOURS = (2, 8, 24, 48, 96)


def send_reminders(requests=None):
	"""Every 15 minutes: remind signers due on REMINDER_HOURS. `requests` limits
	it to those requests (the self-check uses it to leave real ones alone)."""
	if frappe.db.get_single_value("Signature Settings", "disable_reminders"):
		return
	now = now_datetime()
	rows = frappe.db.sql(
		f"""select s.name, s.parent, s.invited_on, s.reminders_sent
		from `tabSignature Request Signer` s
		join `tabSignature Request` r on r.name = s.parent
		where {IN_TURN_SQL}
			and s.invited_on is not null and s.reminders_sent < %(total)s
			and (s.token_expiry is null or s.token_expiry > %(now)s)
			{"and r.name in %(requests)s" if requests else ""}""",
		{"now": now, "total": len(REMINDER_HOURS), "requests": tuple(requests or ())},
		as_dict=True,
	)
	for row in rows:
		hours = (now - row.invited_on).total_seconds() / 3600
		due = sum(1 for h in REMINDER_HOURS if h <= hours)
		if due <= row.reminders_sent:
			continue
		req = frappe.get_doc("Signature Request", row.parent)
		signer = next(s for s in req.signers if s.name == row.name)
		# One email even if several fell due while the scheduler was down.
		signer.db_set("reminders_sent", due, update_modified=False)
		_remind(req, signer)
		frappe.db.commit()


def _remind(request, signer):
	expiry = (
		_(" The link expires on {0}.").format(frappe.utils.format_datetime(signer.token_expiry))
		if signer.token_expiry
		else ""
	)
	_send(
		recipients=[signer.signer_email],
		subject=_("Reminder: Awaiting Signature: {0}").format(request.title),
		message=_(
			"<p>Hello {0},</p>"
			"<p>A reminder that {1} is still waiting for your signature.{2}</p>"
			'<p><a href="{3}">Open and sign {1}</a></p>'
		).format(signer.signer_name, request.title, expiry, _sign_link(signer)),
	)


# ---------------------------------------------------------------------------
# Updating a request nobody has acted on yet
# ---------------------------------------------------------------------------


def _check_can_manage(req):
	"""Whoever may edit the record may manage its request; a standalone request
	(uploaded PDF) belongs to whoever created it."""
	if req.reference_doctype:
		allowed = req.reference_name and frappe.has_permission(req.reference_doctype, "write", req.reference_name)
	else:
		allowed = frappe.has_permission("Signature Request", "write", doc=req)
	if not allowed:
		raise frappe.PermissionError


def _editable_request(request):
	"""The request, if the caller may edit it and nobody has signed or declined.
	A Draft (uploaded PDF, not sent yet) counts: sending it is its first update."""
	req = frappe.get_doc("Signature Request", request, for_update=True)
	_check_can_manage(req)
	if req.status not in ("Draft", "Awaiting Signature") or any(s.status != "Pending" for s in req.signers):
		frappe.throw(
			_("{0} can no longer be changed: someone has already signed or declined it. Request a new signature instead.").format(req.name)
		)
	return req


@frappe.whitelist()
def get_editable_request(request):
	"""Signers and boxes to pre-fill the update dialog. Never returns tokens."""
	req = _editable_request(request)
	return {
		"name": req.name,
		"sign_in_order": req.sign_in_order,
		"signers": [
			{
				"name": s.name,
				"signer_type": s.signer_type,
				"signer_reference": s.signer_reference,
				"signer_name": s.signer_name,
				"signer_email": s.signer_email,
				"sign_boxes": frappe.parse_json(s.sign_boxes) or [],
			}
			for s in req.signers
		],
	}


@frappe.whitelist()
def update_signature_request(request, signers, sign_in_order=None):
	"""Edit a request in place instead of piling up a second one — or send a
	Draft for the first time.

	Kept signers keep their link (so the email they already have still works);
	a changed email counts as a new signer. Removed signers' links stop working.
	A record's PDF is re-rendered so signers see the document as it is now.
	"""
	req = _editable_request(request)
	config = _get_signable_config(req.reference_doctype) if req.reference_doctype else None
	signers = _clean_signers(signers, config)

	old_pdf = req.source_pdf
	if req.reference_doctype:
		pdf = render_source_pdf(req.reference_doctype, req.reference_name, config.default_print_format)
	else:
		pdf = old_pdf and _read_file(old_pdf)
		if not pdf:
			frappe.throw(_("Attach the PDF to be signed first."))
	check_boxes_fit(pdf, signers)

	existing = {row.name: row for row in req.signers}
	rows = []
	for s in signers:
		row = existing.get(s.get("name"))
		if row and (row.signer_email or "").strip().lower() == (s.get("signer_email") or "").strip().lower():
			row.update(_signer_values(s))
			rows.append(row)
		else:
			rows.append(_new_signer_row(s))
	req.set("signers", rows)  # rows left out are deleted on save
	for i, row in enumerate(req.signers, 1):
		row.idx = i  # kept rows keep their old idx otherwise, and the order is who signs next
	req.status = "Awaiting Signature"
	if sign_in_order is not None:
		req.sign_in_order = cint(sign_in_order)

	# Only swap the PDF if the document actually changed since it was sent.
	if req.reference_doctype and pdf != _read_file(old_pdf):
		req.source_pdf = attach_pdf(pdf, f"{req.reference_name}.pdf", req.name, "source_pdf")
	req.flags.from_sign_api = True
	req.save(ignore_permissions=True)
	if old_pdf != req.source_pdf:
		_drop_file(old_pdf, req.name)

	_notify_turn(req)  # new signers, or whoever is now first in line
	return {"name": req.name}


def _clean_signers(signers, config):
	signers = frappe.parse_json(signers) or []
	if not signers:
		frappe.throw(_("At least one signer is required."))
	for s in signers:
		_validate_signer_payload(s, config)
	_validate_unique_signers(signers)
	return signers


def _signer_details(signer_type, reference):
	"""Name and email of a User / Employee / Customer / Supplier signer, from the record."""
	if not reference or not frappe.db.exists(signer_type, reference):
		frappe.throw(_("Pick the {0} who should sign.").format(_(signer_type)))
	if signer_type == "User":
		name, email = frappe.db.get_value("User", reference, ["full_name", "email"])
	elif signer_type == "Employee":
		e = frappe.db.get_value(
			"Employee",
			reference,
			["employee_name", "prefered_email", "company_email", "personal_email", "user_id"],
			as_dict=True,
		)
		name = e.employee_name
		email = e.prefered_email or e.company_email or e.personal_email
		email = email or (e.user_id and frappe.db.get_value("User", e.user_id, "email"))
	else:  # Customer / Supplier: their email, else a linked Contact's, else a linked Address's
		name, email = frappe.db.get_value(signer_type, reference, [f"{signer_type.lower()}_name", "email_id"])
		for linked in ("Contact", "Address") if not email else ():
			found = frappe.get_all(
				linked,
				filters=[
					["Dynamic Link", "link_doctype", "=", signer_type],
					["Dynamic Link", "link_name", "=", reference],
					["email_id", "is", "set"],
				],
				pluck="email_id",
				limit=1,
			)
			if found:
				email = found[0]
				break
	if not email:
		frappe.throw(
			_("{0} {1} has no email address, so they can't be sent a signing link. Raise a support ticket to have an email added to their record, then try again.").format(
				_(signer_type), name or reference
			),
			title=_("No Email Address"),
		)
	return {"signer_name": name or reference, "signer_email": email}


@frappe.whitelist()
def get_default_signers(reference_doctype, reference_name):
	"""The signers a record names itself, to pre-fill the Request Signature dialog.

	A signable doctype opts in by defining get_signers() on its controller. It
	returns a list of dicts, one per signer, in signing order:

		def get_signers(self):
			return [
				{"signer_type": "Employee", "signer_reference": self.employee},
				{"signer_type": "User", "signer_reference": self.approver},
				{"signer_type": "Email", "signer_name": "Jane Doe", "signer_email": "jane@example.com"},
			]

	signer_type       User, Employee, Customer or Supplier: signer_reference is
	                  required, and the name and email are always taken from
	                  that record. Email: signer_email is required, signer_name
	                  optional (defaults to the email). Other types need
	                  Allow External Signers on the Signable Document Type.
	signer_reference  The record's name (User id, Employee id, ...). Not for Email.

	Every entry becomes a signer. An entry that can't be used (no email on the
	record, unknown type, same email twice, empty reference) comes back as a
	warning and the rest still load; so does a get_signers() that raises.
	"""
	if not frappe.has_permission(reference_doctype, "write", reference_name):
		raise frappe.PermissionError
	config = _get_signable_config(reference_doctype)
	doc = frappe.get_doc(reference_doctype, reference_name)
	if not hasattr(doc, "get_signers"):
		return {"signers": [], "warnings": []}
	try:
		entries = doc.get_signers() or []
		if not isinstance(entries, list | tuple):
			raise TypeError("get_signers() must return a list of dicts")
	except Exception:
		frappe.log_error(title=f"Sign: get_signers failed for {reference_doctype} {reference_name}")
		frappe.clear_messages()
		return {"signers": [], "warnings": [_("Couldn't read this document's default signers. Add them by hand.")]}

	signers, warnings, seen = [], [], set()
	for entry in entries:
		entry = frappe._dict(entry if isinstance(entry, dict) else {})
		signer_type = entry.signer_type
		try:
			if signer_type not in SIGNER_TYPES:
				frappe.throw(_("Invalid signer type {0}").format(signer_type))
			if signer_type != "User" and not config.allow_external_signers:
				frappe.throw(_("Only User signers are allowed for {0}.").format(_(reference_doctype)))
			if signer_type == "Email":
				if not entry.signer_email:
					frappe.throw(_("An Email signer in the default signers has no email address."))
				signer = {"signer_name": entry.signer_name or entry.signer_email, "signer_email": entry.signer_email}
			else:
				signer = _signer_details(signer_type, entry.signer_reference)
		except frappe.ValidationError as e:
			warnings.append(str(e))
			continue
		email = signer["signer_email"].strip().lower()
		if email in seen:
			warnings.append(_("{0} is listed more than once; added once.").format(signer["signer_email"]))
			continue
		seen.add(email)
		signers.append(
			{
				**signer,
				"signer_type": signer_type,
				"signer_reference": None if signer_type == "Email" else entry.signer_reference,
			}
		)
	frappe.clear_messages()  # the warnings carry them; don't also pop them up
	return {"signers": signers, "warnings": warnings}


@frappe.whitelist()
def get_signer_details(signer_type, reference):
	"""What the request dialog shows (read-only) once a signer is picked."""
	if signer_type not in SIGNER_TYPES or signer_type == "Email":
		frappe.throw(_("Invalid signer type {0}").format(signer_type))
	if not frappe.has_permission(signer_type, "read", reference):
		raise frappe.PermissionError
	return _signer_details(signer_type, reference)


def _validate_unique_signers(signers):
	"""One row per person: extra places go in that row's sign_boxes."""
	seen = set()
	for s in signers:
		email = (s.get("signer_email") or "").strip().lower()
		if email in seen:
			frappe.throw(_("{0} is added more than once as a signer.").format(s.get("signer_email")))
		seen.add(email)


def _get_signable_config(reference_doctype):
	name = frappe.db.get_value("Signable Document Type", {"document_type": reference_doctype, "enabled": 1})
	if not name:
		frappe.throw(_("{0} is not enabled for signing.").format(reference_doctype))
	return frappe.get_cached_doc("Signable Document Type", name)


def _validate_signer_payload(s, config):
	if s.get("signer_type") not in SIGNER_TYPES:
		frappe.throw(_("Invalid signer type {0}").format(s.get("signer_type")))

	if config and not config.allow_external_signers and s.get("signer_type") != "User":
		frappe.throw(_("Only User signers are allowed for {0}.").format(config.document_type))

	# Anyone but a plain Email signer is taken from their record, never from what
	# was typed: the email is where the link goes and what keys their saved
	# signature, and a User signer also gets their token from their own session.
	if s.get("signer_type") != "Email":
		s.update(_signer_details(s.get("signer_type"), s.get("signer_reference")))

	if not s.get("signer_name") or not s.get("signer_email"):
		frappe.throw(_("Every signer needs a name and an email."))

	# D14 — placement is mandatory: at least one box, as many as the document needs.
	boxes = frappe.parse_json(s.get("sign_boxes")) or []
	if not isinstance(boxes, list) or not boxes:
		frappe.throw(_("Place a signature box for {0} before sending.").format(s.get("signer_name")))
	clean = []
	for b in boxes:
		b = {k: flt((b or {}).get(k)) for k in ("page", "x", "y", "w", "h")}
		if not (b["w"] > 0 and b["h"] > 0) or b["page"] < 0 or b["x"] < 0 or b["y"] < 0:
			frappe.throw(_("A signature box for {0} has no size.").format(s.get("signer_name")))
		b["page"] = int(b["page"])
		clean.append(b)
	s["sign_boxes"] = clean


# ---------------------------------------------------------------------------
# Token validation, shared by 5.2 / 5.3 / 5.4
# ---------------------------------------------------------------------------


def _resolve_signer(key, lock=False):
	"""Return (parent request, signer row) for a valid, still-usable token.

	lock: hold the request's row until commit, so two signers finishing at the
	same moment are merged one after the other instead of over each other."""
	if not key:
		frappe.throw(_("This signing link is not valid."), frappe.PermissionError)

	row = frappe.db.get_value(
		"Signature Request Signer",
		{"access_token": key},
		["name", "parent"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("This signing link is not valid."), frappe.PermissionError)

	request = frappe.get_doc("Signature Request", row.parent, for_update=lock)
	signer = next(s for s in request.signers if s.name == row.name)

	if signer.status != "Pending":
		frappe.throw(
			_("This document has already been {0}.").format(signer.status.lower()), frappe.PermissionError
		)

	# One rejection closes the whole request (3.3) — nobody else can sign it after.
	if request.status == "Rejected":
		frappe.throw(
			_("This document was declined by {0}, so it can no longer be signed.").format(request.rejected_by),
			frappe.PermissionError,
		)
	if request.status == "Withdrawn":
		frappe.throw(
			_("This signature request was withdrawn by the sender, so it can no longer be signed."),
			frappe.PermissionError,
		)

	if signer.token_expiry and now_datetime() > signer.token_expiry:
		frappe.throw(_("This signing link has expired."), frappe.PermissionError)

	if not _is_turn(request, signer):
		first = next(s for s in request.signers if s.status == "Pending")
		frappe.throw(
			_("It's not your turn to sign yet: waiting for {0} to sign first.").format(first.signer_name),
			frappe.PermissionError,
		)

	# D10 — only User signers get a session check; everyone else is token-only.
	if signer.signer_type == "User" and frappe.session.user != "Guest":
		if frappe.session.user != signer.signer_reference:
			frappe.throw(_("This document is not addressed to you."), frappe.PermissionError)

	return request, signer


# ---------------------------------------------------------------------------
# 5.2 get_signing_context
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def get_signing_context(key):
	request, signer = _resolve_signer(key)

	# Return only this signer's own data — never sibling rows (Section 9).
	context = {
		"request_title": request.title,
		"pdf_url": f"/api/method/frappe_sign.frappe_sign.api.download_signing_pdf?key={key}",
		"signer_name": signer.signer_name,
		"signer_type": signer.signer_type,
		"sign_boxes": frappe.parse_json(signer.sign_boxes) or [],
		"saved_signature": _saved_signature_data_url(signer.signer_email),
	}

	return context


def _saved_signature_data_url(email):
	"""The signer's last signature, inlined — the File is private, so a guest
	could not fetch it by URL. The token was mailed to this address, so only
	its owner ever sees it."""
	file_url = frappe.db.get_value("Saved Signature", _email_key(email), "signature")
	content = file_url and _read_file(file_url)
	return "data:image/png;base64," + base64.b64encode(content).decode() if content else None


def _read_file(file_url):
	try:
		with open(file_url_to_path(file_url), "rb") as f:
			return f.read()
	except FileNotFoundError:
		return None


@frappe.whitelist(allow_guest=True)
def download_signing_pdf(key):
	"""Stream the current PDF to whoever holds this signer's token.

	source_pdf / signed_pdf are private Files, so a guest signer cannot fetch
	them by URL — the token is what authorises the read.
	"""
	request, _signer = _resolve_signer(key)
	file_url = request.signed_pdf or request.source_pdf

	with open(file_url_to_path(file_url), "rb") as f:
		frappe.local.response.filecontent = f.read()
	frappe.local.response.filename = file_url.rsplit("/", 1)[-1]
	frappe.local.response.type = "pdf"


# ---------------------------------------------------------------------------
# 5.3 submit_signature
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def submit_signature(key, image_base64, is_upload=False):
	request, signer = _resolve_signer(key, lock=True)

	if not image_base64:
		frappe.throw(_("A signature is required."))

	image_bytes = decode_image(image_base64)
	signed_on = now_datetime()
	signed_ip = _client_ip()

	previous_signed_pdf = request.signed_pdf
	merged = merge_signature(
		request.signed_pdf or request.source_pdf, image_bytes, signer, signed_on, signed_ip
	)
	signed_url = attach_pdf(merged, f"{request.name}-signed.pdf", request.name, "signed_pdf")

	signer.db_set({"status": "Signed", "signed_on": signed_on, "signed_ip": signed_ip})
	request.db_set("signed_pdf", signed_url)
	_drop_file(previous_signed_pdf, request.name)

	_save_signature(signer.signer_email, image_bytes)

	request.reload()
	completed = all(s.status == "Signed" for s in request.signers)
	if completed:
		request.db_set("status", "Signed")
		_set_reference_status(request)
		_email_completed(request)
	else:
		_notify_turn(request)  # in order: the next signer's turn

	# The signature is committed before anything else is attempted: a record
	# that fails to submit must never cost anyone their signature.
	frappe.db.commit()
	if completed:
		_submit_reference(request)
	return {"status": "Signed"}


def _submit_reference(request):
	"""Submit the signed record, if its Signable Document Type says to.

	Runs as the requester, without permission checks — everyone signing is the
	approval. A failure (validation, stock, accounting...) leaves the record in
	draft with a comment saying why; the signed request is untouched.
	"""
	dt, dn = request.reference_doctype, request.reference_name
	if not (dt and dn) or not frappe.db.get_value("Signable Document Type", dt, "submit_when_signed"):
		return
	if not frappe.get_meta(dt).is_submittable or frappe.db.get_value(dt, dn, "docstatus") != 0:
		return
	latest = _latest_request(dt, dn)
	if not latest or latest.name != request.name:
		return  # an older request finishing late never submits

	user = frappe.session.user
	try:
		frappe.set_user(request.created_by_user or "Administrator")
		doc = frappe.get_doc(dt, dn)
		doc.flags.ignore_permissions = True
		doc.submit()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=f"Sign: could not submit {dt} {dn}")
		error = frappe.get_traceback().strip().splitlines()[-1]
		frappe.clear_messages()  # the signer's action succeeded; don't show them this
		frappe.get_doc(dt, dn).add_comment(
			"Comment",
			_("Signed by everyone, but could not be submitted automatically: {0}").format(escape_html(error)),
		)
		frappe.db.commit()
	finally:
		frappe.set_user(user)


def _drop_file(file_url, attached_to_name):
	"""Drop a superseded attachment so copies don't pile up. Scoped to its own
	record: File dedupes by content, so another record may share the URL."""
	if not file_url:
		return
	for name in frappe.get_all("File", {"file_url": file_url, "attached_to_name": attached_to_name}, pluck="name"):
		frappe.delete_doc("File", name, force=True, ignore_permissions=True, delete_permanently=True)


def _email_key(email):
	return (email or "").strip().lower()


def _save_signature(email, image_bytes):
	"""The one intentional store of a signature image: the latest one per email,
	whatever signer type, so the next document can be signed in one click."""
	email = _email_key(email)
	if frappe.db.exists("Saved Signature", email):
		doc = frappe.get_doc("Saved Signature", email)
	else:
		doc = frappe.get_doc({"doctype": "Saved Signature", "email": email}).insert(ignore_permissions=True)

	previous = doc.signature
	if previous and _read_file(previous) == image_bytes:
		return  # signed with the saved one again — nothing to replace
	file_url = save_private_file("signature.png", image_bytes, "Saved Signature", doc.name, "signature")
	doc.db_set("signature", file_url)
	if previous and previous != file_url:
		_drop_file(previous, doc.name)


def _client_ip():
	ip = getattr(frappe.local, "request_ip", None)
	if ip:
		return ip
	request = getattr(frappe.local, "request", None)
	return request.environ.get("REMOTE_ADDR") if request else None


# ---------------------------------------------------------------------------
# 5.4 reject_signature
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def reject_signature(key, reason):
	request, signer = _resolve_signer(key, lock=True)

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is required to decline."))

	signer.db_set({"status": "Rejected", "rejection_reason": reason})
	request.db_set(
		{"status": "Rejected", "rejected_by": signer.signer_name, "rejection_reason": reason}
	)
	_set_reference_status(request)

	_email_rejected(request, signer, reason)
	frappe.db.commit()
	return {"status": "Rejected"}


# ---------------------------------------------------------------------------
# 5.5 get_dashboard_data
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_dashboard_data():
	waiting = frappe.db.sql(
		f"""
		select s.access_token, s.signer_name, r.name as request, r.title,
			r.reference_doctype, r.reference_name
		from `tabSignature Request Signer` s
		join `tabSignature Request` r on r.name = s.parent
		where s.signer_type = 'User' and s.signer_reference = %s and {IN_TURN_SQL}
			and (s.token_expiry is null or s.token_expiry > %s)
		order by r.modified desc
	""",
		(frappe.session.user, now_datetime()),
		as_dict=True,
	)

	sent = frappe.db.sql(
		"""
		select r.name, r.title, r.status, r.reference_doctype, r.reference_name,
			count(s.name) as total,
			sum(case when s.status = 'Signed' then 1 else 0 end) as signed
		from `tabSignature Request` r
		left join `tabSignature Request Signer` s on s.parent = r.name
		where r.created_by_user = %s
		group by r.name
		order by r.modified desc
	""",
		frappe.session.user,
		as_dict=True,
	)

	return {"waiting": waiting, "sent": sent}


# ---------------------------------------------------------------------------
# Section 8 — notifications (plain frappe.sendmail, D16)
# ---------------------------------------------------------------------------


def _sign_link(signer):
	return get_url(f"/sign-document?key={signer.access_token}")


def _send(**kwargs):
	"""Best-effort send. A misconfigured mail server must not lose a signature
	or leave a half-created request behind — log it and carry on, and don't
	surface the mail error as if the signing action itself had failed."""
	messages = len(frappe.message_log)
	try:
		frappe.sendmail(**kwargs)
	except Exception:
		del frappe.message_log[messages:]
		frappe.log_error(title="Sign: could not send notification")


def _email_request_created(request, signer):
	_send(
		recipients=[signer.signer_email],
		subject=_("Awaiting Signature: {0}").format(request.title),
		message=_(
			"<p>Hello {0},</p>"
			"<p>You have a document waiting for your signature:</p>"
			'<p><a href="{1}">Open and sign {2}</a></p>'
		).format(signer.signer_name, _sign_link(signer), request.title),
	)


def _email_rejected(request, signer, reason):
	_send(
		recipients=[request.created_by_user],
		subject=_("Rejected: {0}").format(request.title),
		message=_("<p>Rejected by {0} — {1}</p>").format(signer.signer_name, escape_html(reason)),
	)


def _email_completed(request):
	recipients = [request.created_by_user] + [s.signer_email for s in request.signers]
	_send(
		recipients=list(dict.fromkeys(filter(None, recipients))),
		subject=_("Signed: {0}").format(request.title),
		message=_("<p>{0} has been signed by everyone. The signed copy is attached.</p>").format(
			request.title
		),
		attachments=[{"file_url": request.signed_pdf}],
	)


# ---------------------------------------------------------------------------
# Helpers used by the desk UI
# ---------------------------------------------------------------------------


def boot_session(bootinfo):
	"""Every enabled Signable Document Type, so a form knows on its first paint
	whether Submit must give way to signing — no request, no flash of Submit."""
	bootinfo.frappe_sign = {
		row.document_type: row
		for row in frappe.get_all(
			"Signable Document Type",
			{"enabled": 1},
			[
				"document_type",
				"default_print_format",
				"allow_external_signers",
				"require_signature_to_submit",
				"submit_when_signed",
			],
		)
	}


@frappe.whitelist()
def get_signature_status(reference_doctype, reference_name):
	"""The signers panel on a signable record: its latest request and where each
	signer stands, plus the current user's own signing token if one is waiting.

	Never returns other signers' tokens (Section 9).
	"""
	if not frappe.has_permission(reference_doctype, "read", reference_name):
		raise frappe.PermissionError

	request = _latest_request(reference_doctype, reference_name)
	if not request:
		return None

	return {
		"name": request.name,
		"status": request.status,
		"sign_in_order": request.sign_in_order,
		"rejected_by": request.rejected_by,
		"rejection_reason": request.rejection_reason,
		"earlier_requests": frappe.db.count(
			"Signature Request",
			{"reference_doctype": reference_doctype, "reference_name": reference_name, "name": ("!=", request.name)},
		),
		"signers": [
			{
				"signer_name": s.signer_name,
				"signer_email": s.signer_email,
				"signer_type": s.signer_type,
				"status": s.status,
				"turn": request.status == "Awaiting Signature" and _is_turn(request, s),
				"signed_on": s.signed_on,
				"rejection_reason": s.rejection_reason,
			}
			for s in request.signers
		],
		"my_token": next(
			(
				s.access_token
				for s in request.signers
				if request.status == "Awaiting Signature"
				and _is_turn(request, s)
				and s.signer_type == "User"
				and s.signer_reference == frappe.session.user
			),
			None,
		),
	}


@frappe.whitelist()
def get_request_pdf(request, download=0):
	"""Preview (inline) or download the request's PDF: the signed copy, with
	every signature collected so far, or the unsigned snapshot if nobody has
	signed yet. Readable by anyone who can read the record it belongs to —
	the File itself is private and attached to the request, not the record.
	"""
	req = frappe.get_doc("Signature Request", request)
	if req.reference_doctype and req.reference_name:
		allowed = frappe.has_permission(req.reference_doctype, "read", req.reference_name)
	else:
		allowed = frappe.has_permission("Signature Request", "read", req.name)
	if not allowed:
		raise frappe.PermissionError

	content = _read_file(req.signed_pdf or req.source_pdf) if (req.signed_pdf or req.source_pdf) else None
	if not content:
		frappe.throw(_("The PDF for {0} is missing.").format(req.name))
	suffix = "signed" if req.status == "Signed" else "unsigned" if not req.signed_pdf else "partly-signed"
	frappe.local.response.filename = f"{req.reference_name or req.name}-{suffix}.pdf"
	frappe.local.response.filecontent = content
	frappe.local.response.type = "download" if cint(download) else "pdf"


def _set_reference_status(request):
	"""Mirror the latest request's status onto the record, for its list view.

	Written straight to the column: no modified bump, no save hooks, and it
	works on submitted records too. An older request can't overwrite it.
	"""
	dt, dn = request.reference_doctype, request.reference_name
	if not (dt and dn) or not frappe.get_meta(dt).has_field("signature_status"):
		return
	latest = _latest_request(dt, dn)
	if latest and latest.name == request.name:
		# Withdrawn: the record is back to a plain draft in its list.
		value = "" if request.status == "Withdrawn" else request.status
		frappe.db.set_value(dt, dn, "signature_status", value, update_modified=False)


def _latest_request(reference_doctype, reference_name):
	name = frappe.db.get_value(
		"Signature Request",
		{"reference_doctype": reference_doctype, "reference_name": reference_name},
		"name",
		order_by="creation desc",
	)
	return frappe.get_doc("Signature Request", name) if name else None


def check_signed_before_submit(doc, method=None):
	"""doc_events["*"].before_submit — a signable record whose type requires it
	cannot be submitted until its latest request is signed by everyone."""
	config = frappe.db.get_value(
		"Signable Document Type", doc.doctype, ["enabled", "require_signature_to_submit"], as_dict=True
	)
	if not (config and config.enabled and config.require_signature_to_submit):
		return

	request = _latest_request(doc.doctype, doc.name)
	if request and request.status == "Signed":
		return

	if not request or request.status == "Withdrawn":
		msg = _("Request a signature for this {0} before submitting it.").format(_(doc.doctype))
	elif request.status == "Rejected":
		msg = _("{0} declined to sign ({1}). Request a new signature before submitting.").format(
			request.rejected_by, request.rejection_reason
		)
	else:
		signed = sum(1 for s in request.signers if s.status == "Signed")
		msg = _("This {0} cannot be submitted until everyone has signed: {1} of {2} signed so far.").format(
			_(doc.doctype), signed, len(request.signers)
		)
	frappe.throw(msg, title=_("Signature Required"))


def _locks_record(status, doctype):
	"""A request is "out" while signers may still act on it, or once it is signed
	but the record not yet submitted: either way, what they sign must stay what
	it is. A doctype that can't be submitted has nothing to wait for once signed."""
	return status == "Awaiting Signature" or (status == "Signed" and frappe.get_meta(doctype).is_submittable)


def check_not_out_for_signature(doc, method=None):
	"""doc_events["*"].validate — a draft that is out for signature can't be
	changed from anywhere (form, list, API, import). Submitting still works:
	by then docstatus is 1, and Frappe locks it from there."""
	if doc.docstatus != 0 or doc.is_new():
		return
	if not frappe.db.get_value("Signable Document Type", doc.doctype, "enabled"):
		return
	latest = frappe.db.get_value(
		"Signature Request",
		{"reference_doctype": doc.doctype, "reference_name": doc.name},
		["name", "status"],
		order_by="creation desc",
		as_dict=True,
	)
	if latest and _locks_record(latest.status, doc.doctype):
		frappe.throw(
			_("{0} {1} is out for signature ({2}), so it can't be changed. Withdraw the request to edit it.").format(
				_(doc.doctype), doc.name, latest.name
			),
			title=_("Out for Signature"),
		)


@frappe.whitelist()
def withdraw_signature_request(request):
	"""Take a request back so the record can be edited again.

	Signers' links stop working. Any signatures already given are discarded —
	they were for the version that is about to change. The signed PDF stays on
	the request for the record.
	"""
	req = frappe.get_doc("Signature Request", request, for_update=True)
	_check_can_manage(req)
	# Awaiting: always. Signed: only while its record is still a draft waiting to be submitted.
	if not (
		req.status == "Awaiting Signature"
		or (
			req.reference_doctype
			and _locks_record(req.status, req.reference_doctype)
			and frappe.db.get_value(req.reference_doctype, req.reference_name, "docstatus") == 0
		)
	):
		frappe.throw(_("{0} can't be withdrawn now.").format(req.name))

	req.db_set("status", "Withdrawn")
	req.add_comment("Info", _("Withdrawn by {0}").format(frappe.utils.get_fullname()))
	_set_reference_status(req)
	return {"name": req.name, "status": "Withdrawn"}


@frappe.whitelist()
def merge_pdfs(file_urls):
	"""Join the user's uploaded PDFs, in order, into one document to sign.

	Returns the merged file's URL; the separate uploads are removed. (Word and
	other formats would need LibreOffice on the server, so only PDFs for now.)
	"""
	file_urls = frappe.parse_json(file_urls) or []
	if len(file_urls) < 2:
		frappe.throw(_("Pick at least two PDFs to merge."))
	for url in file_urls:
		check_readable_pdf(url)

	first = file_urls[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
	merged = save_private_file(f"{first}-merged.pdf", merge_pdf_files(file_urls), None, None, None)

	# Only the uploads made for this merge: the caller's own, not attached anywhere.
	for name in frappe.get_all(
		"File",
		{
			"file_url": ("in", file_urls),
			"owner": frappe.session.user,
			"attached_to_doctype": ("is", "not set"),
		},
		pluck="name",
	):
		frappe.delete_doc("File", name, ignore_permissions=True)
	return merged


@frappe.whitelist()
def preview_source_pdf(reference_doctype, reference_name):
	"""Stream the print-format snapshot so the requester can place boxes on it (6.2).

	Streamed rather than stored — a preview that is never sent should not leave
	an orphaned File behind.
	"""
	if not frappe.has_permission(reference_doctype, "write", reference_name):
		raise frappe.PermissionError

	config = _get_signable_config(reference_doctype)
	frappe.local.response.filename = f"{reference_name}.pdf"
	frappe.local.response.filecontent = render_source_pdf(
		reference_doctype, reference_name, config.default_print_format
	)
	frappe.local.response.type = "pdf"
