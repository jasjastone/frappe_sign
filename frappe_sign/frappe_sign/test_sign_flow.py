# Copyright (c) 2026, jasjastone and contributors
# For license information, please see license.txt
"""Phase 8 self-check. Run with:

	bench --site <site> execute frappe_sign.frappe_sign.test_sign_flow.run

Creates and then removes its own data. Asserts only — no test framework.
"""

import base64
import copy
import os

import frappe
from frappe.utils import add_days, now_datetime

from frappe_sign.frappe_sign import api

# 1x1 transparent PNG — enough for PyMuPDF to stamp.
PNG = base64.b64encode(
	base64.b64decode(
		"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
	)
).decode()

BOX = {"page": 0, "x": 60.0, "y": 600.0, "w": 140.0, "h": 45.0}

_created = {"requests": [], "config": None, "supplier": None, "saved_signatures": {}}


def _log(ok, label):
	print(f"  {'PASS' if ok else 'FAIL'}  {label}")
	assert ok, label


def _throws(fn, label):
	try:
		fn()
	except Exception:
		_log(True, label)
		return
	_log(False, label)


def _ref():
	"""A real record to sign — any ToDo will do."""
	return frappe.db.get_value("ToDo", {}, "name")


def _signer(signer_type, reference, name, email, boxes=None):
	return dict(
		signer_type=signer_type,
		signer_reference=reference,
		signer_name=name,
		signer_email=email,
		sign_boxes=boxes or [BOX],
	)


def _create(signers, sign_in_order=0):
	res = api.create_signature_request(
		reference_doctype="ToDo", reference_name=_ref(), signers=signers, sign_in_order=sign_in_order
	)
	_created["requests"].append(res["name"])
	return frappe.get_doc("Signature Request", res["name"])


def _token(request, idx=0):
	return frappe.get_doc("Signature Request", request.name).signers[idx].access_token


def run():
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	# From the CLI there is no request to take the host from, and this site is
	# named after a real public domain — point wkhtmltopdf at the local server.
	frappe.local.conf.host_name = os.environ.get("SIGN_TEST_HOST") or frappe.local.conf.host_name or "http://localhost:8000"
	# No email leaves or is queued: User signers here are real people.
	real_send, api._send = api._send, lambda **kw: None
	setup()
	try:
		test_doctype_enabled_by_one_row()
		test_placement_is_mandatory()
		test_user_signs()
		test_user_rejects()
		test_external_signer_types()
		test_mixed_request_any_order()
		test_rejection_flips_parent_immediately()
		test_expired_token()
		test_second_submit_is_refused()
		test_other_users_token_is_refused()
		test_context_does_not_leak_siblings()
		test_no_signature_image_is_persisted()
		test_signature_is_remembered_per_email()
		test_audit_line_stays_on_page()
		test_one_signature_fills_every_box()
		test_rejected_request_is_closed()
		test_signers_panel()
		test_submit_blocked_until_signed()
		test_request_pdf_preview_and_download()
		test_record_is_submitted_when_signed()
		test_list_status_follows_latest_request()
		test_update_request_in_place()
		test_locked_while_out_for_signature()
		test_hardening()
		test_standalone_request()
		test_merge_pdfs()
		test_sign_in_order()
		test_parallel_notifies_everyone()
		test_status_shows_turn()
		test_dashboard_waits_for_turn()
		test_update_switches_order()
		test_send_reminder()
		test_reminder_schedule()
		test_get_signers()
		print("\nAll checks passed.")
	finally:
		teardown()
		api._send = real_send


# ---------------------------------------------------------------------------


def setup():
	print("\nsetup")
	if not frappe.db.exists("Signable Document Type", "ToDo"):
		frappe.get_doc(
			{
				"doctype": "Signable Document Type",
				"document_type": "ToDo",
				"enabled": 1,
				"default_print_format": None,  # blank -> Frappe's built-in Standard format
				"allow_external_signers": 1,
			}
		).insert()
		_created["config"] = "ToDo"

	if not frappe.db.get_value("Supplier", {}, "name"):
		s = frappe.get_doc(
			{"doctype": "Supplier", "supplier_name": "Sign Test Supplier"}
		).insert(ignore_permissions=True)
		_created["supplier"] = s.name
	# Anything not here at the start was made by these checks and is removed after.
	# Real people's saved signatures, as they are now: a User signer in these
	# checks signs with that user's real email, which replaces theirs.
	_created["saved_signatures"] = {
		s.name: api._read_file(s.signature) if s.signature else None
		for s in frappe.get_all("Saved Signature", ["name", "signature"])
	}
	frappe.db.commit()


def teardown():
	print("\nteardown")
	for name in _created["requests"]:
		frappe.delete_doc("Signature Request", name, force=True, ignore_permissions=True)
	if _created["config"]:
		frappe.delete_doc("Signable Document Type", _created["config"], force=True)
		# enabling ToDo gave it a signature_status field; take it back off
		frappe.delete_doc("Custom Field", "ToDo-signature_status", force=True, ignore_missing=True)
	before = _created["saved_signatures"]
	for s in frappe.get_all("Saved Signature", ["name", "signature"]):
		if s.name not in before:
			frappe.delete_doc("Saved Signature", s.name, force=True, ignore_permissions=True)
		elif before[s.name] and (api._read_file(s.signature) if s.signature else None) != before[s.name]:
			api._save_signature(s.name, before[s.name])  # put theirs back
	if _created["supplier"]:
		frappe.delete_doc("Supplier", _created["supplier"], force=True, ignore_permissions=True)
	frappe.db.commit()


# ---------------------------------------------------------------------------


def test_doctype_enabled_by_one_row():
	print("\nenabling a doctype takes one Signable Document Type row")
	boot = frappe._dict()
	api.boot_session(boot)
	_log("ToDo" in boot.frappe_sign, "ToDo is signable (sent to forms in boot)")
	_log("Note" not in boot.frappe_sign, "Note is not signable (no row, no code)")
	_log(boot.frappe_sign["ToDo"].require_signature_to_submit == 1, "boot carries the submit rule")


def test_placement_is_mandatory():
	print("\nplacement is mandatory (D14)")
	unplaced = {
		"signer_type": "Email",
		"signer_name": "No Box",
		"signer_email": "nobox@example.com",
	}
	_throws(
		lambda: api.create_signature_request(
			reference_doctype="ToDo", reference_name=_ref(), signers=[unplaced]
		),
		"a signer without a placed box is refused",
	)
	_throws(
		lambda: api.create_signature_request(
			reference_doctype="ToDo",
			reference_name=_ref(),
			signers=[_signer("Email", None, "Flat Box", "flat@example.com", [{**BOX, "h": 0}])],
		),
		"a box with no size is refused",
	)
	_throws(
		lambda: api.create_signature_request(
			reference_doctype="ToDo",
			reference_name=_ref(),
			signers=[
				_signer("Email", None, "Same Person", "same@example.com"),
				_signer("Email", None, "Same Person Again", "SAME@example.com"),
			],
		),
		"the same email twice is refused",
	)


def test_user_signs():
	print("\nUser signer, end to end")
	req = _create([_signer("User", "Administrator", "Administrator", "admin@example.com")])
	_log(req.status == "Awaiting Signature", "request is Awaiting Signature")
	_log(bool(req.source_pdf), "print-format snapshot attached as source_pdf")

	api.submit_signature(_token(req), PNG)
	req.reload()
	_log(req.status == "Signed", "parent is Signed once every signer signed")
	_log(bool(req.signed_pdf), "signed_pdf produced")
	_log(req.signers[0].signed_on is not None, "signed_on recorded")


def test_user_rejects():
	print("\nUser signer, reject with reason")
	req = _create([_signer("User", "Administrator", "Administrator", "admin@example.com")])
	api.reject_signature(_token(req), "Wrong amount")
	req.reload()
	_log(req.status == "Rejected", "parent is Rejected")
	_log(req.rejected_by == frappe.db.get_value("User", "Administrator", "full_name"), "rejected_by recorded on the parent (name from the user record)")
	_log(req.rejection_reason == "Wrong amount", "reason mirrored onto the parent")


def test_external_signer_types():
	print("\nEmployee / Customer / Supplier / Email signers, token-only")
	has_email = {
		"Employee": {"company_email": ("is", "set")},
		"Customer": {"email_id": ("is", "set")},
		"Supplier": {"email_id": ("is", "set")},
	}
	cases = [(t, frappe.db.get_value(t, f, "name"), "typed@example.com") for t, f in has_email.items()]
	cases.append(("Email", None, "stranger@example.com"))
	for signer_type, reference, email in cases:
		if signer_type != "Email" and not reference:
			print(f"  SKIP  {signer_type}: no record with an email on this site")
			continue
		req = _create([_signer(signer_type, reference, f"{signer_type} Signer", email)])
		token = _token(req)

		frappe.set_user("Guest")
		ctx = api.get_signing_context(token)
		_log("saved_signature" in ctx, f"{signer_type}: context offers a saved_signature slot")
		api.submit_signature(token, PNG)
		frappe.set_user("Administrator")

		req.reload()
		_log(req.status == "Signed", f"{signer_type}: signed as a guest")
		if reference:
			expected = api._signer_details(signer_type, reference)
			_log(
				(req.signers[0].signer_name, req.signers[0].signer_email)
				== (expected["signer_name"], expected["signer_email"]),
				f"{signer_type}: name and email come from the record, not what was typed",
			)

	for signer_type in has_email:
		bare = _without_email(signer_type)
		if bare:
			_throws(
				lambda: _create([_signer(signer_type, bare, "Typed", "typed@example.com")]),
				f"{signer_type} with no email is refused (typed email ignored)",
			)
	_throws(lambda: api.get_signer_details("Email", "x"), "no lookup for a plain Email signer")


def _without_email(signer_type):
	"""A record the app finds no email for at all (a linked Contact counts)."""
	for name in frappe.get_all(signer_type, pluck="name", limit=200):
		try:
			api._signer_details(signer_type, name)
		except frappe.ValidationError:
			frappe.clear_messages()
			return name


def test_mixed_request_any_order():
	print("\nmixed signer types, signing out of order (D6)")
	req = _create(
		[
			_signer("User", "Administrator", "Administrator", "admin@example.com"),
			_signer("Email", None, "Outsider", "outsider@example.com"),
			_signer("Email", None, "A Customer", "c@example.com"),
		]
	)
	# third, then first, then second
	frappe.set_user("Guest")
	api.submit_signature(_token(req, 2), PNG)
	frappe.set_user("Administrator")
	api.submit_signature(_token(req, 0), PNG)
	req.reload()
	_log(req.status == "Awaiting Signature", "still awaiting while one signer is pending")

	frappe.set_user("Guest")
	api.submit_signature(_token(req, 1), PNG)
	frappe.set_user("Administrator")
	req.reload()
	_log(req.status == "Signed", "Signed only once every signer has signed")


def test_rejection_flips_parent_immediately():
	print("\none rejection rejects the whole request at once (3.3)")
	req = _create(
		[
			_signer("User", "Administrator", "Administrator", "admin@example.com"),
			_signer("Email", None, "Outsider", "outsider@example.com"),
		]
	)
	frappe.set_user("Guest")
	api.reject_signature(_token(req, 1), "Not my contract")
	frappe.set_user("Administrator")
	req.reload()
	_log(req.status == "Rejected", "parent Rejected without waiting for the other signer")
	_log(req.signers[0].status == "Pending", "the other signer row is untouched")


def test_expired_token():
	print("\nexpired token")
	req = _create([_signer("Email", None, "Outsider", "outsider@example.com")])
	token = _token(req)
	frappe.db.set_value(
		"Signature Request Signer", req.signers[0].name, "token_expiry", add_days(now_datetime(), -1)
	)
	frappe.set_user("Guest")
	_throws(lambda: api.get_signing_context(token), "expired token is refused")
	frappe.set_user("Administrator")


def test_second_submit_is_refused():
	print("\nalready signed / already rejected rows are closed")
	req = _create([_signer("Email", None, "Outsider", "outsider@example.com")])
	token = _token(req)
	frappe.set_user("Guest")
	api.submit_signature(token, PNG)
	_throws(lambda: api.submit_signature(token, PNG), "a second submit is refused")
	_throws(lambda: api.reject_signature(token, "changed my mind"), "a later reject is refused")
	frappe.set_user("Administrator")

	req2 = _create([_signer("Email", None, "Outsider", "outsider@example.com")])
	token2 = _token(req2)
	frappe.set_user("Guest")
	api.reject_signature(token2, "no")
	_throws(lambda: api.submit_signature(token2, PNG), "signing after rejecting is refused")
	frappe.set_user("Administrator")


def test_other_users_token_is_refused():
	print("\na logged-in user cannot use someone else's token (D10)")
	other = frappe.db.get_value(
		"User", {"enabled": 1, "name": ("not in", ["Administrator", "Guest"])}, "name"
	)
	req = _create([_signer("User", other, "Someone Else", "someone@example.com")])
	token = _token(req)
	_log(frappe.session.user == "Administrator", f"session is Administrator, token belongs to {other}")
	_throws(lambda: api.get_signing_context(token), "Administrator cannot open another user's token")
	_throws(lambda: api.submit_signature(token, PNG), "Administrator cannot sign for another user")


def test_context_does_not_leak_siblings():
	print("\nget_signing_context returns only the calling signer (Section 9)")
	req = _create(
		[
			_signer("Email", None, "First Signer", "first@example.com"),
			_signer("Email", None, "Second Signer", "second@example.com"),
		]
	)
	frappe.set_user("Guest")
	ctx = api.get_signing_context(_token(req, 0))
	frappe.set_user("Administrator")
	blob = frappe.as_json(ctx)
	_log("Second Signer" not in blob, "sibling name absent")
	_log("second@example.com" not in blob, "sibling email absent")
	_log("signers" not in ctx, "no signer table returned")
	_log(ctx["signer_name"] == "First Signer", "own name is returned")


def test_no_signature_image_is_persisted():
	print("\nno signature image is stored on the request (D9)")
	_log(
		not frappe.get_meta("Signature Request Signer").has_field("signature_image"),
		"no signature_image field on the child table",
	)
	req = _create([_signer("Email", None, "Outsider", "outsider@example.com")])
	frappe.set_user("Guest")
	api.submit_signature(_token(req), PNG)
	frappe.set_user("Administrator")
	req.reload()

	attachments = frappe.get_all(
		"File",
		{"attached_to_doctype": "Signature Request", "attached_to_name": req.name},
		["file_url", "attached_to_field"],
	)
	fields = sorted(a.attached_to_field for a in attachments)
	_log(fields == ["signed_pdf", "source_pdf"], f"only source_pdf + signed_pdf attached, got {fields}")
	_log(
		all(a.file_url.lower().endswith(".pdf") for a in attachments),
		"every attachment is a PDF, no image files",
	)


def _saved_file_count(email):
	return frappe.db.count("File", {"attached_to_doctype": "Saved Signature", "attached_to_name": email})


def test_signature_is_remembered_per_email():
	print("\nthe last signature is remembered per email, guests included")
	email = "remember-me@example.com"
	req = _create([_signer("Email", None, "Remember Me", email)])
	frappe.set_user("Guest")
	ctx = api.get_signing_context(_token(req))
	_log(ctx["saved_signature"] is None, "first document: nothing saved yet")
	api.submit_signature(_token(req), PNG)
	frappe.set_user("Administrator")

	# Same email in a different case — still the same person.
	req2 = _create([_signer("Email", None, "Remember Me", email.upper())])
	frappe.set_user("Guest")
	ctx = api.get_signing_context(_token(req2))
	_log((ctx["saved_signature"] or "").startswith("data:image/png;base64,"), "next document: saved one offered inline")
	_log(ctx["saved_signature"].split(",", 1)[1] == PNG, "it is the image signed last time")

	other = base64.b64encode(_png(2, 2)).decode()
	api.submit_signature(_token(req2), other)
	frappe.set_user("Administrator")
	_log(
		frappe.db.get_value("Saved Signature", email, "signature") is not None
		and api._saved_signature_data_url(email).split(",", 1)[1] == other,
		"signing with a new image replaces the saved one",
	)
	_log(_saved_file_count(email) == 1, "exactly one saved file remains")

	req3 = _create([_signer("Email", None, "Remember Me", email)])
	frappe.set_user("Guest")
	api.submit_signature(_token(req3), other)
	frappe.set_user("Administrator")
	_log(_saved_file_count(email) == 1, "re-signing with the saved one adds no copy")


def _png(w, h):
	import fitz

	pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), 1)
	pix.clear_with(0)
	return pix.tobytes("png")


def test_audit_line_stays_on_page():
	print("\naudit line stays on the page when the box is at the bottom")
	import fitz

	from frappe_sign.frappe_sign.utils import file_url_to_path

	req = _create([_signer("Email", None, "Bottom Signer", "bottom@example.com")])
	with fitz.open(file_url_to_path(req.source_pdf)) as doc:
		height = doc[0].rect.height
	frappe.db.set_value(
		"Signature Request Signer",
		req.signers[0].name,
		"sign_boxes",
		frappe.as_json([{**BOX, "y": height - 45, "h": 40}]),
	)
	frappe.set_user("Guest")
	api.submit_signature(_token(req), PNG)
	frappe.set_user("Administrator")
	req.reload()

	with fitz.open(file_url_to_path(req.signed_pdf)) as doc:
		hits = doc[0].search_for("Signed by Bottom Signer")
	_log(bool(hits) and all(0 <= r.y0 and r.y1 <= height for r in hits), "audit text found inside the page")


def test_one_signature_fills_every_box():
	print("\none signer, several places: one signature fills every box")
	import fitz

	from frappe_sign.frappe_sign.utils import file_url_to_path

	boxes = [BOX, {**BOX, "y": 300.0}, {**BOX, "x": 350.0, "y": 450.0}]
	req = _create([_signer("Email", None, "Many Places", "many@example.com", boxes)])
	frappe.set_user("Guest")
	ctx = api.get_signing_context(_token(req))
	_log(len(ctx["sign_boxes"]) == 3, "context returns all three boxes")
	api.submit_signature(_token(req), PNG)
	frappe.set_user("Administrator")
	req.reload()

	# The snapshot may carry its own images (letter head logo), so count what signing added.
	with fitz.open(file_url_to_path(req.source_pdf)) as doc:
		before = len(doc[0].get_image_info())
	with fitz.open(file_url_to_path(req.signed_pdf)) as doc:
		added = len(doc[0].get_image_info()) - before
		audits = doc[0].search_for("Signed by Many Places")
	_log(added == 3, f"signature stamped three times, got {added}")
	_log(len(audits) == 3, f"an audit line under each box, got {len(audits)}")


def test_rejected_request_is_closed():
	print("\nonce declined, nobody else can sign the request")
	req = _create(
		[
			_signer("Email", None, "Decliner", "decliner@example.com"),
			_signer("Email", None, "Latecomer", "latecomer@example.com"),
		]
	)
	frappe.set_user("Guest")
	api.reject_signature(_token(req, 0), "Wrong price")
	_throws(lambda: api.get_signing_context(_token(req, 1)), "the other signer cannot open it")
	_throws(lambda: api.submit_signature(_token(req, 1), PNG), "the other signer cannot sign it")
	frappe.set_user("Administrator")


def test_signers_panel():
	print("\nsigners panel shows each signer's status, never tokens")
	ref = _ref()
	req = _create(
		[
			_signer("User", "Administrator", "Administrator", "admin@example.com"),
			_signer("Email", None, "Outsider", "outsider@example.com"),
		]
	)
	frappe.set_user("Guest")
	api.reject_signature(_token(req, 1), "Not my contract")
	frappe.set_user("Administrator")

	status = api.get_signature_status("ToDo", ref)
	_log(status["name"] == req.name, "latest request is shown")
	by_name = {s["signer_name"]: s for s in status["signers"]}
	_log(by_name["Outsider"]["status"] == "Rejected", "declined signer shows Rejected")
	_log(by_name["Outsider"]["rejection_reason"] == "Not my contract", "with their reason")
	_log(by_name[frappe.db.get_value("User", "Administrator", "full_name")]["status"] == "Pending", "the other signer shows Pending")
	_log(status["my_token"] is None, "no Sign button on a rejected request")
	blob = frappe.as_json({k: v for k, v in status.items() if k != "my_token"})
	_log(_token(req, 0) not in blob and _token(req, 1) not in blob, "no signer tokens in the panel data")


def test_submit_blocked_until_signed():
	print("\na signable record cannot be submitted until signed")
	# ToDo isn't submittable, so call the before_submit hook directly.
	doc = frappe._dict(doctype="ToDo", name=_ref())
	for name in frappe.get_all("Signature Request", {"reference_doctype": "ToDo", "reference_name": doc.name}, pluck="name"):
		frappe.delete_doc("Signature Request", name, force=True, ignore_permissions=True)

	_throws(lambda: api.check_signed_before_submit(doc), "no request yet: submit blocked")
	req = _create([_signer("Email", None, "Outsider", "outsider@example.com")])
	_throws(lambda: api.check_signed_before_submit(doc), "awaiting signature: submit blocked")
	frappe.set_user("Guest")
	api.submit_signature(_token(req), PNG)
	frappe.set_user("Administrator")
	api.check_signed_before_submit(doc)
	_log(True, "signed by everyone: submit allowed")

	frappe.db.set_value("Signable Document Type", "ToDo", "require_signature_to_submit", 0)
	req2 = _create([_signer("Email", None, "Outsider", "outsider@example.com")])
	api.check_signed_before_submit(doc)
	_log(True, "requirement switched off: submit allowed while awaiting")
	frappe.db.set_value("Signable Document Type", "ToDo", "require_signature_to_submit", 1)


def test_request_pdf_preview_and_download():
	print("\nthe request PDF can be previewed or downloaded by readers of the record")
	req = _create([_signer("Email", None, "Outsider", "outsider@example.com")])
	frappe.set_user("Guest")
	api.submit_signature(_token(req), PNG)
	_throws(lambda: api.get_request_pdf(req.name), "a guest cannot fetch it")
	frappe.set_user("Administrator")

	api.get_request_pdf(req.name)
	r = frappe.local.response
	_log(r.type == "pdf" and r.filecontent.startswith(b"%PDF"), "preview streams the PDF inline")
	_log(r.filename.endswith("-signed.pdf"), f"fully signed copy is named as such, got {r.filename}")
	api.get_request_pdf(req.name, download=1)
	_log(frappe.local.response.type == "download", "download sends it as an attachment")


def test_record_is_submitted_when_signed():
	print("\nthe record is submitted once everyone has signed")
	# ToDo isn't submittable: stand in for its meta and document just for this check.
	real_get_meta, real_get_doc = frappe.get_meta, frappe.get_doc
	events = []

	class Stub:
		def __init__(self, fail=False):
			self.flags, self.fail = frappe._dict(), fail

		def submit(self):
			events.append(("submit", frappe.session.user, self.flags.ignore_permissions))
			if self.fail:
				frappe.throw("Stock is short")

		def add_comment(self, _type, text):
			events.append(("comment", text))

	stub = {"doc": Stub()}

	def get_meta(dt, *a, **k):
		meta = real_get_meta(dt, *a, **k)
		if dt == "ToDo":
			meta = copy.copy(meta)
			meta.is_submittable = 1
		return meta

	def get_doc(*a, **k):
		if len(a) == 2 and a[0] == "ToDo":
			return stub["doc"]
		return real_get_doc(*a, **k)

	def sign_new_request():
		req = _create([_signer("Email", None, "Outsider", "outsider@example.com")])
		frappe.get_doc = get_doc
		frappe.get_meta = get_meta
		try:
			frappe.set_user("Guest")
			api.submit_signature(_token(req), PNG)
		finally:
			frappe.get_doc, frappe.get_meta = real_get_doc, real_get_meta
			frappe.set_user("Administrator")
		return frappe.get_doc("Signature Request", req.name)

	sign_new_request()
	_log(events == [("submit", "Administrator", True)], f"submitted as the requester, got {events}")

	events.clear()
	stub["doc"] = Stub(fail=True)
	req = sign_new_request()
	_log(events[0][0] == "submit" and events[1][0] == "comment", "a failed submit leaves a comment")
	_log("Stock is short" in events[1][1], "the comment says why")
	_log(type(frappe.message_log) is not list, "the per-request message log is left in place")
	_log(req.status == "Signed", "the signature is kept")

	events.clear()
	stub["doc"] = Stub()
	frappe.db.set_value("Signable Document Type", "ToDo", "submit_when_signed", 0)
	sign_new_request()
	frappe.db.set_value("Signable Document Type", "ToDo", "submit_when_signed", 1)
	_log(events == [], "setting off: nothing submitted")


def test_list_status_follows_latest_request():
	print("\nthe record carries its latest request's status, for the list view")
	_log(frappe.get_meta("ToDo").has_field("signature_status"), "enabling a type added signature_status")
	ref = _ref()
	status = lambda: frappe.db.get_value("ToDo", ref, "signature_status")
	modified = frappe.db.get_value("ToDo", ref, "modified")

	older = _create([_signer("Email", None, "Outsider", "outsider@example.com")])
	_log(status() == "Awaiting Signature", "sent: Awaiting Signature")
	frappe.set_user("Guest")
	api.reject_signature(_token(older), "no")
	frappe.set_user("Administrator")
	_log(status() == "Rejected", "declined: Rejected")

	latest = _create(
		[_signer("Email", None, "One", "one@example.com"), _signer("Email", None, "Two", "two@example.com")]
	)
	_log(status() == "Awaiting Signature", "new request: back to Awaiting Signature")
	frappe.set_user("Guest")
	api.submit_signature(_token(latest, 0), PNG)
	_log(status() == "Awaiting Signature", "one of two signed: still Awaiting Signature")
	api.submit_signature(_token(latest, 1), PNG)
	frappe.set_user("Administrator")
	_log(status() == "Signed", "everyone signed: Signed")

	api._set_reference_status(frappe.get_doc("Signature Request", older.name))
	_log(status() == "Signed", "an older request can't overwrite it")
	_log(frappe.db.get_value("ToDo", ref, "modified") == modified, "the record's modified time is untouched")


def test_update_request_in_place():
	print("\na request nobody has acted on can be fixed in place")
	req = _create(
		[
			_signer("Email", None, "Keeper", "keeper@example.com"),
			_signer("Email", None, "Dropped", "dropped@example.com"),
		]
	)
	keeper_token, dropped_token = _token(req, 0), _token(req, 1)
	old_pdf = req.source_pdf
	count = lambda: frappe.db.count("Signature Request", {"reference_doctype": "ToDo", "reference_name": req.reference_name})
	before = count()

	editable = api.get_editable_request(req.name)
	_log("access_token" not in frappe.as_json(editable), "edit data carries no tokens")
	keeper = next(s for s in editable["signers"] if s["signer_name"] == "Keeper")
	moved = {**BOX, "y": 200.0}
	api.update_signature_request(
		req.name,
		[
			{**keeper, "sign_boxes": [moved, BOX]},  # kept, now two places
			_signer("Email", None, "Forgotten", "forgotten@example.com"),  # the one they forgot
		],
	)
	req.reload()
	_log(count() == before, "no second request was created")
	_log([s.signer_name for s in req.signers] == ["Keeper", "Forgotten"], "signer list replaced")
	_log(_token(req, 0) == keeper_token, "the kept signer's link still works")
	_log(len(frappe.parse_json(req.signers[0].sign_boxes)) == 2, "the kept signer's boxes were updated")
	_log(req.source_pdf == old_pdf, "document unchanged: same PDF kept")
	source_files = lambda: frappe.db.count(
		"File", {"attached_to_name": req.name, "attached_to_field": "source_pdf"}
	)
	_log(source_files() == 1, "and no duplicate attachment")

	# The user edits the document, then updates the request: signers get the new version.
	description = frappe.db.get_value("ToDo", req.reference_name, "description")
	frappe.db.set_value("ToDo", req.reference_name, "description", f"{description} (edited)")
	api.update_signature_request(req.name, api.get_editable_request(req.name)["signers"])
	frappe.db.set_value("ToDo", req.reference_name, "description", description)
	req.reload()
	_log(req.source_pdf != old_pdf, "document edited: PDF re-rendered")
	_log(source_files() == 1, "the old PDF was dropped")
	_log(_token(req, 0) == keeper_token, "the kept signer's link survives a second update")
	frappe.set_user("Guest")
	_throws(lambda: api.get_signing_context(dropped_token), "the removed signer's link is dead")
	api.submit_signature(_token(req, 0), PNG)
	frappe.set_user("Administrator")

	_throws(lambda: api.get_editable_request(req.name), "once someone signed, it can't be edited")
	_throws(
		lambda: api.update_signature_request(req.name, [_signer("Email", None, "Late", "late@example.com")]),
		"and an update is refused",
	)


def test_locked_while_out_for_signature():
	print("\nthe record is locked while out for signature; withdrawing unlocks it")
	ref = _ref()
	original = frappe.db.get_value("ToDo", ref, "description")

	def edit(text):
		doc = frappe.get_doc("ToDo", ref)
		doc.description = text
		doc.save()

	req = _create(
		[_signer("Email", None, "One", "one@example.com"), _signer("Email", None, "Two", "two@example.com")]
	)
	_throws(lambda: edit("changed while awaiting"), "awaiting signature: saving is refused")
	frappe.set_user("Guest")
	api.submit_signature(_token(req, 0), PNG)
	frappe.set_user("Administrator")
	_throws(lambda: edit("changed after one signed"), "partly signed: still refused")

	# submitting passes the lock (docstatus is 1 by the time validate runs)
	submitting = frappe._dict(doctype="ToDo", name=ref, docstatus=1, is_new=lambda: False)
	api.check_not_out_for_signature(submitting)
	_log(True, "submitting is not blocked by the lock")

	api.withdraw_signature_request(req.name)
	req.reload()
	_log(req.status == "Withdrawn", "withdrawn")
	_log(not frappe.db.get_value("ToDo", ref, "signature_status"), "list status back to plain draft")
	frappe.set_user("Guest")
	_throws(lambda: api.get_signing_context(_token(req, 1)), "the remaining signer's link is dead")
	frappe.set_user("Administrator")
	_throws(lambda: api.withdraw_signature_request(req.name), "a withdrawn request can't be withdrawn again")
	_throws(
		lambda: api.check_signed_before_submit(frappe._dict(doctype="ToDo", name=ref)),
		"withdrawn doesn't count as signed for submitting",
	)
	edit("edited after withdrawing")
	_log(frappe.db.get_value("ToDo", ref, "description") == "edited after withdrawing", "editable again")

	declined = _create([_signer("Email", None, "No", "no@example.com")])
	frappe.set_user("Guest")
	api.reject_signature(_token(declined), "no")
	frappe.set_user("Administrator")
	edit(original)
	_log(frappe.db.get_value("ToDo", ref, "description") == original, "declined: editable, to fix and re-request")


def _other_user():
	return frappe.db.get_value(
		"User", {"enabled": 1, "user_type": "System User", "name": ("not in", ["Administrator", "Guest"])}, "name"
	)


def test_hardening():
	print("\nv1 hardening")
	from frappe_sign.frappe_sign.utils import file_url_to_path

	for url in ("/private/../site_config.json", "/private/files/../../site_config.json", "/etc/passwd", "../x"):
		_throws(lambda: file_url_to_path(url), f"path outside the site's files is refused: {url}")

	victim = "victim@example.com"
	req = _create([_signer("User", "Administrator", "Administrator", victim)])
	_log(req.signers[0].signer_email != victim, "a User signer's email is always the user's own")
	api.withdraw_signature_request(req.name)

	_throws(
		lambda: _create([_signer("Email", None, "Far", "far@example.com", [{**BOX, "page": 9}])]),
		"a box on a page the PDF doesn't have is refused",
	)
	_throws(
		lambda: _create([_signer("Email", None, "Off", "off@example.com", [{**BOX, "x": 5000.0}])]),
		"a box off the page is refused",
	)

	mixed = _create(
		[_signer("User", "Administrator", "Administrator", ""), _signer("Email", None, "No", "no@example.com")]
	)
	waiting = lambda: [w.request for w in api.get_dashboard_data()["waiting"]]
	_log(mixed.name in waiting(), "dashboard lists a request waiting for me")
	frappe.set_user("Guest")
	api.reject_signature(_token(mixed, 1), "no")
	frappe.set_user("Administrator")
	_log(mixed.name not in waiting(), "and drops it once someone declined")

	# ToDo can't be submitted: once signed there is nothing to wait for, so it unlocks.
	signed = _create([_signer("Email", None, "One", "one@example.com")])
	frappe.set_user("Guest")
	api.submit_signature(_token(signed), PNG)
	frappe.set_user("Administrator")
	doc = frappe.get_doc("ToDo", signed.reference_name)
	doc.save()
	_log(True, "non-submittable record: editable once signed")
	_throws(lambda: api.withdraw_signature_request(signed.name), "and its signed request can't be withdrawn")


def test_standalone_request():
	print("\na standalone PDF (letter, office document) signed without a record")
	from frappe_sign.frappe_sign.utils import render_source_pdf, save_private_file

	user = _other_user()
	pdf = render_source_pdf("ToDo", _ref())
	frappe.set_user(user)
	try:
		file_url = save_private_file("letter.pdf", pdf, None, None, None)
		req = frappe.get_doc({"doctype": "Signature Request", "source_pdf": file_url}).insert()
		_created["requests"].append(req.name)
		_log(req.status == "Draft" and req.created_by_user == user, "saved from the form as a Draft")
		_log(req.title == file_url.rsplit("/", 1)[-1], f"title defaults to the file name ({req.title})")

		for label, bad in (
			("an arbitrary path", "/private/files/../../site_config.json"),
			("a file they can't read", next(
				(f.file_url for f in frappe.get_all(
					"File", {"is_private": 1, "owner": ("!=", user), "file_url": ("like", "%.pdf")}, ["name", "file_url"], limit=200
				) if not frappe.has_permission("File", "read", f.name)),
				None,
			)),
		):
			_log(bool(bad), f"found {label} to try")
			if bad:
				_throws(
					lambda: frappe.get_doc({"doctype": "Signature Request", "source_pdf": bad}).insert(),
					f"{label} can't be used as the PDF",
				)
		_throws(
			lambda: frappe.get_doc({"doctype": "Signature Request", "source_pdf": file_url, "status": "Signed"}).insert(),
			"can't be created already Signed",
		)

		api.update_signature_request(req.name, [_signer("Email", None, "Tenant", "tenant@example.com")])
		req.reload()
		_log(req.status == "Awaiting Signature", "sent with Request Signature")
		seen = frappe.client.get("Signature Request", req.name)
		_log(not seen["signers"][0].get("access_token"), "the requester can't read the signer's token")
		_log(
			not any(r.get("access_token") for r in frappe.get_list(
				"Signature Request Signer", parent_doctype="Signature Request", fields=["name", "access_token"]
			)),
			"not through the list API either",
		)
		req.status = "Signed"
		_throws(req.save, "the requester can't mark it Signed")
	finally:
		frappe.set_user("Administrator")

	frappe.set_user("Guest")
	api.submit_signature(_token(req), PNG)
	frappe.set_user("Administrator")
	req.reload()
	_log(req.status == "Signed" and bool(req.signed_pdf), "signed by the guest")


def _pdf(*sizes):
	"""A PDF with one blank page per (width, height) — page size tells them apart."""
	import fitz

	with fitz.open() as doc:
		for w, h in sizes:
			doc.new_page(width=w, height=h)
		return doc.tobytes()


def test_merge_pdfs():
	print("\nseveral PDFs merged into one document to sign")
	import fitz

	from frappe_sign.frappe_sign.utils import file_url_to_path, save_private_file

	user = _other_user()
	frappe.set_user(user)
	try:
		a = save_private_file("part-a.pdf", _pdf((200, 200)), None, None, None)
		b = save_private_file("part-b.pdf", _pdf((300, 300), (400, 400)), None, None, None)
		merged = api.merge_pdfs([b, a])
		with fitz.open(file_url_to_path(merged)) as doc:
			sizes = [int(p.rect.width) for p in doc]
		_log(sizes == [300, 400, 200], f"pages joined in the order given, got {sizes}")
		_log(merged.startswith("/private/files/"), "merged PDF saved as a private file")
		_log(
			not frappe.db.exists("File", {"file_url": ("in", [a, b]), "owner": user}),
			"the separate uploads are removed",
		)

		c = save_private_file("part-c.pdf", _pdf((200, 200)), None, None, None)
		txt = save_private_file("notes.txt", b"not a pdf", None, None, None)
		fake = save_private_file("fake.pdf", b"not a pdf either", None, None, None)
		_throws(lambda: api.merge_pdfs([c, txt]), "a non-PDF file is refused")
		_throws(lambda: api.merge_pdfs([c, fake]), "a broken PDF is refused")
		_throws(lambda: api.merge_pdfs([c, "/private/files/../../site_config.json"]), "an arbitrary path is refused")
		_throws(lambda: api.merge_pdfs([c]), "one file is not a merge")
		theirs = next(
			(f.file_url for f in frappe.get_all(
				"File", {"is_private": 1, "owner": ("!=", user), "file_url": ("like", "%.pdf")}, ["name", "file_url"], limit=200
			) if not frappe.has_permission("File", "read", f.name)),
			None,
		)
		if theirs:
			_throws(lambda: api.merge_pdfs([c, theirs]), "a file they can't read is refused")
		_log(bool(frappe.db.exists("File", {"file_url": c})), "a refused merge deletes nothing")

		req = frappe.get_doc({"doctype": "Signature Request", "source_pdf": merged}).insert()
		_created["requests"].append(req.name)
		_log(req.title.endswith("-merged.pdf"), "the merged PDF is accepted as the document to sign")
	finally:
		frappe.set_user("Administrator")
		for url in (c, txt, fake):
			for name in frappe.get_all("File", {"file_url": url}, pluck="name"):
				frappe.delete_doc("File", name, force=True, ignore_permissions=True)


# ---------------------------------------------------------------------------
# Signing order and reminders


def _row(request, idx):
	return frappe.get_doc("Signature Request", request.name).signers[idx]


def _three(prefix):
	return [_signer("Email", None, f"{prefix} {i}", f"{prefix.lower()}-{i}@example.com") for i in range(3)]


def _not_your_turn(token, label):
	frappe.set_user("Guest")
	try:
		api.get_signing_context(token)
		ok = False
	except frappe.PermissionError as e:
		ok = "not your turn" in str(e)
	finally:
		frappe.set_user("Administrator")
	_log(ok, label)


def test_sign_in_order():
	print("\nsigning in order: one signer at a time, top to bottom")
	req = _create(_three("Order"), sign_in_order=1)
	_log(req.sign_in_order == 1, "request is in order")
	rows = frappe.get_doc("Signature Request", req.name).signers
	_log(bool(rows[0].invited_on and rows[0].token_expiry), "first signer invited, link clock started")
	_log(
		not any(r.invited_on or r.token_expiry for r in rows[1:]),
		"the others are not invited yet, and their links have no expiry",
	)
	_not_your_turn(_token(req, 1), "second signer is told it's not their turn")
	_not_your_turn(_token(req, 2), "third signer is told it's not their turn")
	frappe.set_user("Guest")
	_throws(lambda: api.submit_signature(_token(req, 1), PNG), "and can't sign ahead of the first")
	api.submit_signature(_token(req, 0), PNG)
	frappe.set_user("Administrator")

	_log(bool(_row(req, 1).invited_on and _row(req, 1).token_expiry), "first signed: second is invited")
	_log(not _row(req, 2).invited_on, "third still waits")
	_not_your_turn(_token(req, 2), "third is still refused")
	frappe.set_user("Guest")
	api.get_signing_context(_token(req, 1))
	api.submit_signature(_token(req, 1), PNG)
	api.submit_signature(_token(req, 2), PNG)
	frappe.set_user("Administrator")
	req.reload()
	_log(req.status == "Signed", "all three signed in turn: Signed")


def test_parallel_notifies_everyone():
	print("\nnot in order (default): everyone is invited at once")
	req = _create(_three("Parallel"))
	rows = frappe.get_doc("Signature Request", req.name).signers
	_log(req.sign_in_order == 0, "sign_in_order defaults to off")
	_log(all(r.invited_on and r.token_expiry for r in rows), "all three invited on create")
	frappe.set_user("Guest")
	api.get_signing_context(_token(req, 2))
	frappe.set_user("Administrator")
	_log(True, "the last signer can open it straight away")


def test_status_shows_turn():
	print("\nthe signers panel shows whose turn it is")
	ref = _ref()
	req = _create(_three("Panel"), sign_in_order=1)
	status = api.get_signature_status("ToDo", ref)
	_log(status["name"] == req.name and status["sign_in_order"] == 1, "panel says the request is in order")
	_log([s["turn"] for s in status["signers"]] == [True, False, False], "only the first signer's turn")
	frappe.set_user("Guest")
	api.submit_signature(_token(req, 0), PNG)
	frappe.set_user("Administrator")
	status = api.get_signature_status("ToDo", ref)
	_log([s["turn"] for s in status["signers"]] == [False, True, False], "after the first signs: the second's turn")


def test_dashboard_waits_for_turn():
	print("\ndashboard lists a request only once it's my turn")
	req = _create(
		[
			_signer("Email", None, "Goes First", "goes-first@example.com"),
			_signer("User", "Administrator", "Administrator", ""),
		],
		sign_in_order=1,
	)
	waiting = lambda: [w.request for w in api.get_dashboard_data()["waiting"]]
	_log(req.name not in waiting(), "second in line: not on my dashboard yet")
	ref = req.reference_name
	_log(api.get_signature_status("ToDo", ref)["my_token"] is None, "and no Sign button for me yet")
	frappe.set_user("Guest")
	api.submit_signature(_token(req, 0), PNG)
	frappe.set_user("Administrator")
	_log(req.name in waiting(), "first signed: now it's on my dashboard")
	_log(api.get_signature_status("ToDo", ref)["my_token"] == _token(req, 1), "and my Sign button appears")


def test_update_switches_order():
	print("\nupdating a request can switch the order on or off")
	req = _create(_three("Switch"), sign_in_order=1)
	signers = api.get_editable_request(req.name)["signers"]
	_log(api.get_editable_request(req.name)["sign_in_order"] == 1, "edit data carries sign_in_order")

	# Move the third (never invited) signer to the top.
	api.update_signature_request(req.name, [signers[2], signers[0], signers[1]])
	req.reload()
	_log(req.sign_in_order == 1, "left out: sign_in_order kept")
	_log([s.signer_name for s in req.signers] == ["Switch 2", "Switch 0", "Switch 1"], "new order saved")
	_log(bool(req.signers[0].invited_on and req.signers[0].token_expiry), "moved to first: invited now")
	_log(not req.signers[2].invited_on, "the one still waiting is not invited")
	_not_your_turn(req.signers[1].access_token, "the old first signer now waits their turn")

	api.update_signature_request(req.name, api.get_editable_request(req.name)["signers"], sign_in_order=0)
	req.reload()
	_log(req.sign_in_order == 0, "switched off")
	_log(all(s.invited_on for s in req.signers), "everyone is invited once the order is off")

	api.update_signature_request(req.name, api.get_editable_request(req.name)["signers"], sign_in_order=1)
	req.reload()
	_log(req.sign_in_order == 1, "switched back on")
	_not_your_turn(req.signers[2].access_token, "last in line is refused again")


class _Outbox(list):
	"""Stands in for api._send: records each mail instead of sending it."""

	def __enter__(self):
		self.real, api._send = api._send, lambda **kw: self.append(kw)
		return self

	def __exit__(self, *exc):
		api._send = self.real

	def to(self, *emails):
		return [m for m in self if set(m["recipients"]) & set(emails)]


def test_send_reminder():
	print("\nremind now: only whoever the request is waiting on")
	req = _create(_three("Remind"), sign_in_order=1)
	emails = [f"remind-{i}@example.com" for i in range(3)]
	before = _row(req, 0).invited_on
	with _Outbox() as out:
		reminded = api.send_reminder(req.name)
	_log(reminded == ["Remind 0"], f"returns who was reminded, got {reminded}")
	_log(len(out.to(*emails)) == 1 and out.to(emails[0]), "one email, to the first signer")
	_log("Reminder" in out.to(emails[0])[0]["subject"], "it is a reminder")
	_log(_row(req, 0).invited_on == before and not _row(req, 0).reminders_sent, "an extra email: the schedule is untouched")
	_log(not _row(req, 1).invited_on, "the others are left alone")

	parallel = _create(_three("RemindAll"))
	with _Outbox() as out:
		api.send_reminder(parallel.name)
	_log(len(out.to(*[f"remindall-{i}@example.com" for i in range(3)])) == 3, "not in order: everyone reminded")

	frappe.set_user("Guest")
	api.reject_signature(_token(req, 0), "no")
	frappe.set_user("Administrator")
	_throws(lambda: api.send_reminder(req.name), "a rejected request can't be reminded")
	api.withdraw_signature_request(parallel.name)
	_throws(lambda: api.send_reminder(parallel.name), "a withdrawn request can't be reminded")


def test_reminder_schedule():
	print("\nreminders 2h, 8h, 1 day, 2 days and 4 days after the document reaches a signer")
	from datetime import timedelta

	original = frappe.db.get_single_value("Signature Settings", "disable_reminders")

	def invited(req, idx, hours_ago):
		frappe.db.set_value(
			"Signature Request Signer", _row(req, idx).name, "invited_on", now_datetime() - timedelta(hours=hours_ago)
		)

	def remind(*reqs):
		with _Outbox() as out:
			api.send_reminders([r.name for r in reqs])  # only these: real requests are left alone
		return out

	try:
		frappe.db.set_single_value("Signature Settings", "disable_reminders", 0)
		req = _create(_three("Sched"), sign_in_order=1)
		first = "sched-0@example.com"
		invited(req, 0, 1)
		_log(not remind(req).to(first), "1 hour in: nothing yet")
		invited(req, 0, 2.1)
		_log(len(remind(req).to(first)) == 1, "2 hours: first reminder")
		_log(not remind(req).to(first), "run again straight away: not sent twice")
		sent = []
		for hours in (8.1, 24.1, 48.1, 96.1):
			invited(req, 0, hours)
			sent.append(len(remind(req).to(first)))
		_log(sent == [1, 1, 1, 1], f"8 hours, 1 day, 2 days, 4 days: one each, got {sent}")
		_log(_row(req, 0).reminders_sent == 5, "five reminders in all")
		invited(req, 0, 300)
		_log(not remind(req).to(first), "after the last one: no more")
		invited(req, 1, 50)
		_log(not remind(req).to("sched-1@example.com"), "not their turn: not reminded")

		late = _create([_signer("Email", None, "Late", "late@example.com")])
		invited(late, 0, 30)  # the scheduler was down: 2h, 8h and 1 day all passed
		_log(len(remind(late).to("late@example.com")) == 1, "several due at once: one email, not a burst")
		_log(_row(late, 0).reminders_sent == 3, "and the missed ones count as sent")

		expired = _create([_signer("Email", None, "Expired", "expired@example.com")])
		invited(expired, 0, 3)
		frappe.db.set_value(
			"Signature Request Signer", _row(expired, 0).name, "token_expiry", add_days(now_datetime(), -1)
		)
		_log(not remind(expired).to("expired@example.com"), "link expired: not reminded")

		off = _create([_signer("Email", None, "Off", "off@example.com")])
		invited(off, 0, 3)
		frappe.db.set_single_value("Signature Settings", "disable_reminders", 1)
		_log(not remind(off), "reminders disabled: nothing sent")
	finally:
		frappe.db.set_single_value("Signature Settings", "disable_reminders", original or 0)
		frappe.db.commit()

def test_get_signers():
	print("\na doctype names its own signers with get_signers()")
	from frappe.desk.doctype.todo.todo import ToDo

	ref = _ref()
	get = lambda: api.get_default_signers("ToDo", ref)
	_log(get() == {"signers": [], "warnings": []}, "no get_signers(): nothing pre-filled")

	admin = frappe.db.get_value("User", "Administrator", ["full_name", "email"], as_dict=True)
	no_email = _without_email("Customer")
	ToDo.get_signers = lambda self: [
		{"signer_type": "Email", "signer_name": "First Out", "signer_email": "first-out@example.com"},
		{"signer_type": "User", "signer_reference": "Administrator"},
		{"signer_type": "Email", "signer_email": "FIRST-OUT@example.com"},  # same person again
		{"signer_type": "Customer", "signer_reference": no_email},
		{"signer_type": "Robot", "signer_reference": "x"},
		{"signer_reference": "Administrator"},  # no type
		{"signer_type": "Email", "signer_email": ["not", "text"]},
		{"signer_type": "User", "signer_reference": {"a": 1}},
		{"signer_type": ["User"], "signer_reference": "Administrator"},
		"not a dict",
	]
	try:
		res = get()
		got = [(s["signer_type"], s["signer_name"], s["signer_email"]) for s in res["signers"]]
		_log(
			got == [("Email", "First Out", "first-out@example.com"), ("User", admin.full_name, admin.email)],
			f"signers in the order given, details from the record, got {got}",
		)
		_log(res["signers"][1]["signer_reference"] == "Administrator", "the record is kept as the reference")
		warnings = " ".join(res["warnings"])
		_log("more than once" in warnings, "a duplicate email is added once, with a warning")
		_log(warnings.count("Invalid signer type") == 4, "an unknown, missing or malformed type is a warning, not a failure")
		_log("no email address" in warnings and "Pick the User" in warnings, "a malformed email or reference is a warning too")
		if no_email:
			_log("support ticket" in warnings, "a record with no email is a warning telling them to raise a ticket")
		_log(not frappe.message_log, "nothing pops up besides the warnings")

		# What get_signers() returns goes straight into a request once boxes are placed.
		req = _create([{**s, "sign_boxes": [BOX]} for s in res["signers"]], sign_in_order=1)
		_log([s.signer_email for s in req.signers] == ["first-out@example.com", admin.email], "and can be sent as is")

		def broken(self):
			raise Exception("typo in get_signers")

		ToDo.get_signers = broken
		res = get()
		_log(res["signers"] == [] and res["warnings"], "a broken get_signers(): a warning, the dialog still opens")
		ToDo.get_signers = lambda self: {"signer_type": "User"}
		_log(get()["signers"] == [] and get()["warnings"], "not a list: a warning")

		ToDo.get_signers = lambda self: [{"signer_type": "Email", "signer_email": "ext@example.com"}]
		frappe.db.set_value("Signable Document Type", "ToDo", "allow_external_signers", 0)
		frappe.clear_document_cache("Signable Document Type", "ToDo")
		try:
			res = get()
		finally:
			frappe.db.set_value("Signable Document Type", "ToDo", "allow_external_signers", 1)
			frappe.clear_document_cache("Signable Document Type", "ToDo")
		_log(not res["signers"] and "Only User signers" in res["warnings"][0], "external signers off: a warning")
	finally:
		del ToDo.get_signers

	if no_email:
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Sign Test",
				"email_ids": [{"email_id": "linked-contact@example.com", "is_primary": 1}],
				"links": [{"link_doctype": "Customer", "link_name": no_email}],
			}
		).insert(ignore_permissions=True)
		try:
			email = api._signer_details("Customer", no_email)["signer_email"]
			_log(email == "linked-contact@example.com", "a customer with no email uses its linked contact's")
		finally:
			frappe.delete_doc("Contact", contact.name, force=True, ignore_permissions=True)
			frappe.db.commit()
