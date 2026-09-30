/**
 * Injects "Request Signature" (7.1) and "Sign" (7.3) onto any doctype that has
 * an enabled Signable Document Type row. No per-doctype code anywhere (D4).
 */
frappe.provide("frappe_sign");

// Enabled Signable Document Types, from boot (see api.boot_session).
frappe_sign.signable_config = (doctype) => (frappe.boot.frappe_sign || {})[doctype];

/** Must this record be signed before it can be submitted? */
frappe_sign.is_gated = (frm, config) =>
	config.require_signature_to_submit &&
	frm.meta.is_submittable &&
	frm.doc.docstatus === 0 &&
	!frm.is_dirty(); // unsaved edits: the toolbar shows Save, leave it alone

// --- List view & form header: signing status on drafts ------------------------
// A draft shows where its signing stands instead of plain "Draft". Once it is
// submitted, the doctype's own status (Unpaid, Overdue, ...) takes over untouched.
const SIGN_INDICATORS = {
	"Awaiting Signature": [__("Awaiting Signature"), "orange"],
	Signed: [__("Signed"), "green"],
	Rejected: [__("Signature Declined"), "red"],
};

const core_get_indicator = frappe.get_indicator;
frappe.get_indicator = function (doc, doctype, ...rest) {
	const dt = doctype || doc.doctype;
	const ind = doc.docstatus === 0 && !doc.__unsaved && frappe_sign.signable_config(dt) && SIGN_INDICATORS[doc.signature_status];
	return ind ? [...ind, `signature_status,=,${doc.signature_status}`] : core_get_indicator.call(this, doc, doctype, ...rest);
};

// Fetch signature_status with the list's own query — no extra request.
const core_set_fields = frappe.views.ListView.prototype.set_fields;
frappe.views.ListView.prototype.set_fields = async function () {
	await core_set_fields.call(this);
	if (frappe_sign.signable_config(this.doctype)) this._add_field("signature_status");
};

// Never draw Submit on a record that still needs signing. The toolbar draws its
// main button before form scripts run, so hiding it from refresh() would leave
// Submit clickable for a moment; this stops it being drawn at all. The signing
// button takes the slot once the status loads, and Submit returns when signed.
const toolbar_status = frappe.ui.form.Toolbar.prototype.get_action_status;
frappe.ui.form.Toolbar.prototype.get_action_status = function () {
	const status = toolbar_status.call(this);
	const config = status === "Submit" && frappe_sign.signable_config(this.frm.doctype);
	return config && frappe_sign.is_gated(this.frm, config) ? null : status;
};

frappe.ui.form.on("*", {
	refresh(frm) {
		const config = frappe_sign.signable_config(frm.doctype);
		if (!config || frm.is_new()) return;

		frappe
			.xcall("frappe_sign.frappe_sign.api.get_signature_status", {
				reference_doctype: frm.doctype,
				reference_name: frm.doc.name,
			})
			.then((status) => {
				if (status) frappe_sign.render_signers(frm, status);
				frappe_sign.set_sign_actions(frm, config, status);
			});
	},
});

/**
 * Put the next signing step where people look: the main button.
 *
 * If this type must be signed before submitting, Submit is swapped for whatever
 * the record needs next — Request Signature, Sign, or Awaiting Signatures — and
 * only comes back once everyone has signed (the server enforces the same rule).
 * Otherwise Submit stays and Sign is added as a highlighted button beside it.
 */
frappe_sign.set_sign_actions = function (frm, config, status) {
	const sign = () => frappe_sign.open_sign_dialog(status.my_token, frm);
	const request = () => frappe_sign.open_request_dialog(frm, config);
	const gated = frappe_sign.is_gated(frm, config);
	const can_write = frm.perm[0]?.write; // read before locking changes it
	const draft = frm.doc.docstatus === 0;

	// One request at a time: a new one only when there is none, or it was declined
	// or withdrawn. While nobody has acted it can be fixed in place. While it is
	// out (or signed, not yet submitted) the record is locked; withdrawing unlocks.
	const needs_request = !status || ["Rejected", "Withdrawn"].includes(status.status);
	// Signed only keeps a record locked while it waits to be submitted.
	const out =
		draft && status && (status.status === "Awaiting Signature" || (status.status === "Signed" && frm.meta.is_submittable));
	const untouched =
		status && status.status === "Awaiting Signature" && status.signers.every((s) => s.status === "Pending");
	const can_request = can_write && (draft || !config.require_signature_to_submit);

	if (out) frappe_sign.lock_form(frm);
	if (can_write && untouched) {
		frm.add_custom_button(__("Update Signature Request"), () =>
			frappe_sign.open_request_dialog(frm, config, status.name)
		);
	}
	if (can_write && out) frm.add_custom_button(__("Withdraw Request"), () => frappe_sign.withdraw(frm, status));
	if (can_write && status && status.status === "Awaiting Signature") {
		frm.add_custom_button(__("Send Reminder"), () => frappe_sign.send_reminder(status.name));
	}
	if (can_request && needs_request && !gated) {
		frm.add_custom_button(__("Request Signature"), request); // gated records get it as the main button
	}

	if (out) {
		frm.dashboard.clear_comment();
		frm.dashboard.add_comment(
			__("This document is out for signature, so it can't be edited. Withdraw the request to edit it."),
			"orange",
			true
		);
	} else if (gated) {
		// Replaces Frappe's "Submit this document to confirm", which isn't true yet.
		frm.dashboard.clear_comment();
		frm.dashboard.add_comment(__("This document must be signed by everyone before it can be submitted."), "orange", true);
	}

	if (!gated) {
		if (status && status.my_token) {
			frm.add_custom_button(__("Sign"), sign).removeClass("btn-default").addClass("btn-primary");
		}
		return;
	}

	if (status && status.my_token) {
		frm.page.set_primary_action(__("Sign"), sign, "edit");
	} else if (needs_request) {
		frm.page.set_primary_action(__("Request Signature"), request);
	} else if (status.status === "Signed") {
		// Everyone signed (usually already auto-submitted; this is the fallback).
		frm.page.set_primary_action(__("Submit"), () => frm.savesubmit());
	} else {
		const signed = status.signers.filter((s) => s.status === "Signed").length;
		frm.page.set_primary_action(__("Awaiting Signatures ({0}/{1})", [signed, status.signers.length]), () =>
			frm.layout.wrapper.find(".frappe-sign-status-section")[0]?.scrollIntoView({ behavior: "smooth" })
		);
	}
};

/**
 * Fields read-only for this refresh only (Frappe recomputes frm.perm on the next).
 * Only write is dropped: a signed draft must still be submittable. The server
 * enforces the same lock (api.check_not_out_for_signature).
 */
frappe_sign.lock_form = function (frm) {
	frm.perm = frm.perm.map((p) => ({ ...p, write: 0 }));
	frm.refresh_fields();
};

frappe_sign.send_reminder = function (request) {
	frappe.xcall("frappe_sign.frappe_sign.api.send_reminder", { request }).then((names) =>
		frappe.show_alert({ message: __("Reminder sent to {0}", [names.join(", ")]), indicator: "green" })
	);
};

frappe_sign.withdraw = function (frm, status) {
	const signed = status.signers.filter((s) => s.status === "Signed").length;
	const msg = signed
		? __("Withdraw {0}? The {1} signature(s) already given will be discarded, and you can edit the document again.", [status.name, signed])
		: __("Withdraw {0}? Signers' links will stop working, and you can edit the document again.", [status.name]);
	frappe.confirm(msg, () =>
		frappe.xcall("frappe_sign.frappe_sign.api.withdraw_signature_request", { request: status.name }).then(() => {
			frappe.show_alert({ message: __("Signature request withdrawn"), indicator: "orange" });
			frm.reload_doc();
		})
	);
};

/** The "Signers" section on a signable record: every signer and where they stand. */
frappe_sign.render_signers = function (frm, status) {
	const colors = { Signed: "green", Rejected: "red", Pending: "orange", "Awaiting Signature": "orange" };
	const pill = (s) => `<span class="indicator-pill ${colors[s] || "gray"}">${__(s)}</span>`;
	const esc = frappe.utils.escape_html;

	const rows = status.signers
		.map(
			(s, i) => `<tr>
				<td>${status.sign_in_order ? `${i + 1}. ` : ""}${esc(s.signer_name)}<div class="text-muted small">${esc(s.signer_email)}</div></td>
				<td>${__(s.signer_type)}</td>
				<td>${pill(s.status)}</td>
				<td>${
					s.status === "Signed"
						? frappe.datetime.str_to_user(s.signed_on)
						: s.status === "Rejected"
						? `<span class="text-danger">${esc(s.rejection_reason || "")}</span>`
						: `<span class="text-muted">${s.turn ? __("Waiting for signature") : __("Waiting for their turn")}</span>`
				}</td>
			</tr>`
		)
		.join("");
	const signed = status.signers.filter((s) => s.status === "Signed").length;

	const html = `
		<div class="frappe-sign-status">
			<div class="sign-status-head">
				<div>${pill(status.status)} <span class="text-muted">${__("{0} of {1} signed", [signed, status.signers.length])}</span></div>
				<div>
					<button class="btn btn-xs btn-default sign-preview">${__(status.status === "Signed" ? "Preview Signed PDF" : "Preview PDF")}</button>
					<a class="btn btn-xs btn-default" href="${frappe_sign.request_pdf_url(status.name, 1)}">${__("Download")}</a>
					<a href="/app/signature-request/${encodeURIComponent(status.name)}">${esc(status.name)}</a>
				</div>
			</div>
			<table class="table table-sm table-bordered mb-0">
				<thead><tr><th>${__("Signer")}</th><th>${__("Type")}</th><th>${__("Status")}</th><th>${__("Signed On / Reason")}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
			${
				status.earlier_requests
					? `<div class="text-muted small mt-2">${__("{0} earlier request(s) on this document.", [status.earlier_requests])}
						<a href="/app/signature-request?reference_doctype=${encodeURIComponent(frm.doctype)}&reference_name=${encodeURIComponent(frm.doc.name)}">${__("View all")}</a></div>`
					: ""
			}
		</div>`;

	// Top of the first visible tab (Details / Overview), not tucked under Connections.
	// refresh() can fire twice before the first status call returns, so replace.
	frm.layout.wrapper.find(".frappe-sign-status-section").remove();
	const tab = frm.layout.tabs.find((t) => !t.is_hidden());
	// form-dashboard-section, not form-section: Frappe's refresh_sections() hides
	// any .form-section in a tab that holds no form fields, which is this one.
	const $section = $(`<div class="form-dashboard-section card-section frappe-sign-status-section">
			<div class="section-head">${__("Signers")}</div>
			<div class="section-body">${html}</div>
		</div>`).prependTo(tab ? tab.wrapper : frm.layout.wrapper);
	$section.find(".sign-preview").on("click", () => frappe_sign.preview_pdf(status.name));
};

frappe_sign.request_pdf_url = function (request, download) {
	return (
		`/api/method/frappe_sign.frappe_sign.api.get_request_pdf?request=${encodeURIComponent(request)}` +
		(download ? "&download=1" : "")
	);
};

/** Look at the PDF in the browser's own viewer, then decide whether to download it. */
frappe_sign.preview_pdf = function (request) {
	const d = new frappe.ui.Dialog({
		title: request,
		size: "extra-large",
		primary_action_label: __("Download"),
		primary_action: () => window.open(frappe_sign.request_pdf_url(request, 1)),
	});
	$(`<iframe class="sign-preview-frame" src="${frappe_sign.request_pdf_url(request)}"></iframe>`).appendTo(d.body);
	d.show();
};

/** 7.3 — mount the shared widget in a Dialog. */
frappe_sign.open_sign_dialog = function (token, frm, after) {
	const d = new frappe.ui.Dialog({ title: __("Sign"), size: "large" });
	d.show();
	frappe_sign.mount_sign_widget(d.body, token, {
		on_done: (status) => {
			d.hide();
			frappe.show_alert({ message: status === "Signed" ? __("Signed") : __("Rejected"), indicator: "green" });
			if (frm) frm.reload_doc();
			if (after) after();
		},
	});
};

/**
 * 7.1 — signer picker + mandatory placement (6.2).
 *
 * frm is the signable record, or a standalone Signature Request (an uploaded
 * PDF), which is sent — or updated — through update_signature_request.
 */
frappe_sign.open_request_dialog = async function (frm, config, request_name) {
	await frappe_sign.load_libs();
	const standalone = frm.doctype === "Signature Request";
	const sending = !request_name || (standalone && frm.doc.status === "Draft");

	const signers = [];
	const COLORS = ["#2490ef", "#e2495e", "#29cd42", "#f4a93a", "#9a5cf3", "#16b4c4"];
	const DEFAULT_BOX = { w: 160, h: 50 }; // PDF points
	let next_color = 0;
	let active = null; // the signer the next click on the document places
	let in_order = 0;

	// Updating: start from the request's own signers and boxes (row names kept,
	// so the server can tell kept signers — whose links stay valid — from new ones).
	if (request_name) {
		const existing = await frappe.xcall("frappe_sign.frappe_sign.api.get_editable_request", {
			request: request_name,
		});
		existing.signers.forEach((s) => signers.push({ ...s, color: COLORS[next_color++ % COLORS.length] }));
		in_order = existing.sign_in_order;
		active = signers[0] || null;
	} else if (!standalone) {
		// A doctype can name its own signers with get_signers() on its controller.
		// Defaults are a convenience: if they can't load, open the dialog empty
		// (xcall has already shown the error) so signers can still be added by hand.
		const defaults = await frappe
			.xcall("frappe_sign.frappe_sign.api.get_default_signers", {
				reference_doctype: frm.doctype,
				reference_name: frm.doc.name,
			})
			.catch(() => ({ signers: [], warnings: [] }));
		defaults.signers.forEach((s) =>
			signers.push({ sign_boxes: [], ...s, color: COLORS[next_color++ % COLORS.length] })
		);
		// A withdrawn/declined request brings its own order; get_signers() lists are in signing order.
		in_order = defaults.sign_in_order ?? (signers.length > 1 ? 1 : 0);
		active = signers[0] || null;
		if (defaults.warnings.length) {
			frappe.msgprint({
				title: __("Some default signers were left out"),
				indicator: "orange",
				message: defaults.warnings.map((w) => `<p>${w}</p>`).join(""), // escaped on the server
			});
		}
	}

	const d = new frappe.ui.Dialog({
		title: sending ? __("Request Signature") : __("Update Signature Request {0}", [request_name]),
		size: "extra-large",
		fields: [
			{
				fieldname: "signer_type",
				fieldtype: "Select",
				label: __("Signer Type"),
				options: config.allow_external_signers
					? ["User", "Employee", "Customer", "Supplier", "Email"]
					: ["User"],
				default: "User",
				onchange: () => on_type_change(),
			},
			{
				fieldname: "signer_reference",
				fieldtype: "Dynamic Link",
				label: __("Signer Reference"),
				options: "signer_type",
				onchange: () => prefill_from_reference(),
			},
			{ fieldname: "cb_signer", fieldtype: "Column Break" },
			{ fieldname: "signer_name", fieldtype: "Data", label: __("Signer Name") },
			{ fieldname: "signer_email", fieldtype: "Data", label: __("Signer Email"), options: "Email" },
			{
				fieldname: "add_signer",
				fieldtype: "Button",
				label: __("Add Signer"),
				click: () => add_signer(),
			},
			{ fieldname: "sb_list", fieldtype: "Section Break" },
			{
				fieldname: "sign_in_order",
				fieldtype: "Check",
				label: __("Signers sign in order (top to bottom)"),
				description: __("Each signer is emailed when the one before them has signed."),
				default: in_order,
				onchange: () => render_list(),
			},
			{ fieldname: "signer_list", fieldtype: "HTML" },
			{ fieldname: "sb_place", fieldtype: "Section Break", label: __("Placement") },
			{ fieldname: "placement", fieldtype: "HTML" },
		],
		primary_action_label: sending ? __("Request Signature") : __("Update"),
		primary_action: () => submit(),
	});
	d.show();

	// Only a plain Email signer is typed in. Everyone else comes from their record
	// (the server takes it from there too, whatever is sent).
	function on_type_change() {
		const is_email = d.get_value("signer_type") === "Email";
		d.set_df_property("signer_reference", "hidden", is_email);
		d.set_df_property("signer_name", "read_only", !is_email);
		d.set_df_property("signer_email", "read_only", !is_email);
		d.set_values({ signer_reference: "", signer_name: "", signer_email: "" });
	}
	on_type_change();

	// The link re-fires onchange when it blurs, i.e. when Add Signer is clicked. Blanking
	// the read-only name/email then hides them, the button jumps up and the click is lost,
	// so skip a signer already fetched and only overwrite (never blank) while fetching.
	let prefilled = null;
	async function prefill_from_reference() {
		const type = d.get_value("signer_type");
		const ref = d.get_value("signer_reference");
		if (`${type}:${ref}` === prefilled) return;
		prefilled = `${type}:${ref}`;
		if (!ref || type === "Email") {
			d.set_values({ signer_name: "", signer_email: "" });
			return;
		}
		// No email on the record: the server's message says to raise a ticket for it.
		const details = await frappe
			.xcall("frappe_sign.frappe_sign.api.get_signer_details", { signer_type: type, reference: ref })
			.catch(() => {
				prefilled = null;
				return { signer_name: "", signer_email: "" };
			});
		if (d.get_value("signer_reference") === ref) d.set_values(details); // still the one picked
	}

	async function add_signer() {
		const row = {
			signer_type: d.get_value("signer_type"),
			signer_reference: d.get_value("signer_reference") || null,
			signer_name: d.get_value("signer_name"),
			signer_email: d.get_value("signer_email"),
			color: COLORS[next_color % COLORS.length],
			sign_boxes: [], // [{ page, x, y, w, h }] in PDF points — one per place they sign
		};
		if (row.signer_type !== "Email" && !row.signer_reference) {
			frappe.msgprint(__("Pick the {0} who should sign.", [__(row.signer_type)]));
			return;
		}
		if (row.signer_type !== "Email") {
			// Clicking Add can beat prefill_from_reference (the click's blur even restarts
			// it), so fetch the record's details here rather than read half-filled fields.
			Object.assign(
				row,
				await frappe.xcall("frappe_sign.frappe_sign.api.get_signer_details", {
					signer_type: row.signer_type,
					reference: row.signer_reference,
				})
			);
		}
		if (!row.signer_name || !row.signer_email) {
			frappe.msgprint(__("Every signer needs a name and an email."));
			return;
		}
		const email = row.signer_email.trim().toLowerCase();
		const twin = signers.find((s) => s.signer_email.trim().toLowerCase() === email);
		if (twin) {
			frappe.msgprint(__("{0} is already a signer. To have them sign in more places, select them and click the document again.", [frappe.utils.escape_html(twin.signer_name)]));
			return;
		}
		next_color++;
		signers.push(row);
		d.set_value("signer_reference", "");
		d.set_value("signer_name", "");
		d.set_value("signer_email", "");
		set_active(row); // the one just added is the one you place next
	}

	function render_list() {
		const ordered = d.get_value("sign_in_order");
		const rows = signers
			.map(
				(s, i) => `<tr class="sign-signer-row ${s === active ? "is-active" : ""}" data-i="${i}" style="--c:${s.color}">
					<td>${
						ordered
							? `<span class="sign-order">
								<a class="sign-move ${i ? "" : "invisible"}" data-by="-1" title="${__("Move up")}">↑</a>
								<a class="sign-move ${i < signers.length - 1 ? "" : "invisible"}" data-by="1" title="${__("Move down")}">↓</a>
								${i + 1}.</span> `
							: ""
					}<span class="sign-signer-swatch" style="background:${s.color}"></span>${frappe.utils.escape_html(s.signer_name)}</td>
					<td>${frappe.utils.escape_html(s.signer_email)}</td>
					<td>${s.signer_type}</td>
					<td>${
						s.sign_boxes.length
							? `${
									s.sign_boxes.length === 1 ? __("1 place") : __("{0} places", [s.sign_boxes.length])
							  } · <a class="sign-goto">${__("Go to box")}</a>`
							: `<span class="text-danger">${__("Not placed")}</span>`
					}</td>
					<td><a class="text-danger sign-remove">${__("Remove")}</a></td>
				</tr>`
			)
			.join("");
		const $w = $(d.fields_dict.signer_list.wrapper).html(
			signers.length
				? `<div class="sign-signers-scroll"><table class="table table-bordered table-sm"><thead><tr>
						<th>${__("Name")}</th><th>${__("Email")}</th><th>${__("Type")}</th>
						<th>${__("Box")}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
				: `<div class="text-muted">${__("No signers added yet.")}</div>`
		);
		const signer_of = (e) => signers[$(e.currentTarget).closest("tr").data("i")];
		$w.find(".sign-signer-row").on("click", (e) => set_active(signer_of(e)));
		$w.find(".sign-goto").on("click", (e) => {
			e.stopPropagation();
			const s = signer_of(e);
			set_active(s);
			scroll_to(s);
		});
		$w.find(".sign-move").on("click", (e) => {
			e.stopPropagation();
			const i = +$(e.currentTarget).closest("tr").data("i");
			const j = i + +e.currentTarget.dataset.by;
			[signers[i], signers[j]] = [signers[j], signers[i]];
			render_list();
		});
		$w.find(".sign-remove").on("click", (e) => {
			e.stopPropagation();
			const s = signer_of(e);
			signers.splice(signers.indexOf(s), 1);
			set_active(active === s ? signers.find((x) => !x.sign_boxes.length) || null : active);
		});
	}

	// --- 6.2 placement: each click adds a box, drag to move, corner to resize ---
	// A signer can have as many boxes as the document needs; every box stays on
	// the document and stays editable until the request is sent.
	const $place = $(d.fields_dict.placement.wrapper);
	const pages = []; // [{ el, canvas, scale }] — scale: canvas px per PDF point
	const pdf_url = standalone
		? frappe_sign.request_pdf_url(frm.doc.name)
		: `/api/method/frappe_sign.frappe_sign.api.preview_source_pdf` +
		  `?reference_doctype=${encodeURIComponent(frm.doctype)}&reference_name=${encodeURIComponent(frm.doc.name)}`;

	function set_active(s) {
		active = s;
		render_list();
		draw_boxes();
		$place.find(".sign-place-hint").text(
			active
				? __(
						"Click wherever {0} should sign; each click adds another place. Drag a box to move it, its corner to resize it, or × to remove it.",
						[active.signer_name]
				  )
				: __("Add a signer above, then click on the document where they should sign.")
		);
	}

	const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));

	/** A box given in canvas pixels, as PDF points (pdf.js and PyMuPDF share a top-left origin). */
	function to_points(page_idx, px) {
		const sc = pages[page_idx].scale;
		return { page: page_idx, x: px.x / sc, y: px.y / sc, w: px.w / sc, h: px.h / sc };
	}

	function remove_box(s, box) {
		s.sign_boxes.splice(s.sign_boxes.indexOf(box), 1);
		set_active(s);
	}

	function scroll_to(s) {
		const box = s.sign_boxes[0];
		const page = box && pages[box.page];
		if (!page) return;
		$place.find(".sign-place-wrap")[0].scrollTop = page.el.offsetTop + box.y * page.scale - 40;
	}

	function draw_boxes() {
		$place.find(".sign-place-box").remove();
		signers.forEach((s) => {
			s.sign_boxes.forEach((box, i) => {
				const page = pages[box.page];
				if (!page) return;
				const $b = $(`<div class="sign-place-box">
						<span class="sign-place-label"></span>
						<span class="sign-place-remove" title="${__("Remove")}">&times;</span>
						<span class="sign-place-resize"></span>
					</div>`)
					.css({ left: box.x * page.scale, top: box.y * page.scale, width: box.w * page.scale, height: box.h * page.scale })
					.toggleClass("is-active", s === active)
					.appendTo(page.el);
				$b[0].style.setProperty("--c", s.color);
				$b.find(".sign-place-label").text(s.sign_boxes.length > 1 ? `${s.signer_name} · ${i + 1}` : s.signer_name);
				$b.find(".sign-place-remove").on("click", () => remove_box(s, box));
				$b[0].addEventListener("pointerdown", (e) => drag_box(e, s, box, $b[0]));
			});
		});
	}

	/** Move (body) or resize (corner) an existing box. Commits to points on release. */
	function drag_box(e, s, box, el) {
		if (e.target.classList.contains("sign-place-remove")) return;
		e.preventDefault();
		e.stopPropagation();
		const { canvas } = pages[box.page];
		const resizing = e.target.classList.contains("sign-place-resize");
		const start = { x: e.clientX, y: e.clientY, left: el.offsetLeft, top: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
		el.setPointerCapture(e.pointerId);

		const move = (ev) => {
			const dx = ev.clientX - start.x;
			const dy = ev.clientY - start.y;
			if (resizing) {
				el.style.width = clamp(start.w + dx, 30, canvas.width - start.left) + "px";
				el.style.height = clamp(start.h + dy, 15, canvas.height - start.top) + "px";
			} else {
				el.style.left = clamp(start.left + dx, 0, canvas.width - start.w) + "px";
				el.style.top = clamp(start.top + dy, 0, canvas.height - start.h) + "px";
			}
		};
		const up = () => {
			el.removeEventListener("pointermove", move);
			el.removeEventListener("pointerup", up);
			el.removeEventListener("pointercancel", up);
			Object.assign(box, to_points(box.page, { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight }));
			set_active(s);
		};
		el.addEventListener("pointermove", move);
		el.addEventListener("pointerup", up);
		el.addEventListener("pointercancel", up);
	}

	/** Click on a page adds a default-size box there; click-and-drag draws one. */
	function bind_page(page_idx) {
		const { canvas } = pages[page_idx];

		function at(e) {
			const r = canvas.getBoundingClientRect();
			return { x: clamp(e.clientX - r.left, 0, r.width), y: clamp(e.clientY - r.top, 0, r.height) };
		}

		canvas.addEventListener("pointerdown", (e) => {
			if (!active) {
				frappe.show_alert({ message: __("Add a signer first."), indicator: "orange" });
				return;
			}
			e.preventDefault(); // else Chrome starts a native image-drag and eats the move events
			canvas.setPointerCapture(e.pointerId);
			const s = active;
			const a = at(e);
			let box = null; // created once the pointer has moved far enough to count as a drag

			const move = (ev) => {
				const b = at(ev);
				if (!box && Math.abs(b.x - a.x) < 10 && Math.abs(b.y - a.y) < 10) return;
				const pts = to_points(page_idx, { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) });
				if (box) Object.assign(box, pts);
				else s.sign_boxes.push((box = pts));
				draw_boxes();
			};
			const up = () => {
				canvas.removeEventListener("pointermove", move);
				canvas.removeEventListener("pointerup", up);
				canvas.removeEventListener("pointercancel", up);
				if (!box) {
					const sc = pages[page_idx].scale;
					const w = DEFAULT_BOX.w * sc;
					const h = DEFAULT_BOX.h * sc;
					s.sign_boxes.push(
						to_points(page_idx, {
							x: clamp(a.x - w / 2, 0, canvas.width - w),
							y: clamp(a.y - h / 2, 0, canvas.height - h),
							w,
							h,
						})
					);
				}
				set_active(s);
			};
			canvas.addEventListener("pointermove", move);
			canvas.addEventListener("pointerup", up);
			canvas.addEventListener("pointercancel", up);
		});
	}

	async function render_document() {
		$place.html(`
			<div class="mb-2 sign-place-hint"></div>
			<div class="sign-place-wrap"><div class="text-muted p-3">${__("Rendering document...")}</div></div>
		`);
		set_active(active);
		const $wrap = $place.find(".sign-place-wrap");
		let pdf;
		try {
			pdf = await window.pdfjsLib.getDocument(pdf_url).promise;
		} catch (e) {
			$wrap.html(`<div class="text-danger p-3">${__("Could not render the document for placement.")}</div>`);
			return;
		}
		$wrap.empty();
		// An uploaded PDF can arrive before the dialog has finished opening (no width yet).
		for (let i = 0; !$place.width() && i < 60; i++) await new Promise(requestAnimationFrame);
		const width = Math.min($place.width() - 20, 760);
		for (let n = 1; n <= pdf.numPages; n++) {
			const $page = $(`<div class="sign-place-page"><canvas></canvas></div>`).appendTo($wrap);
			const canvas = $page.find("canvas")[0];
			const viewport = await frappe_sign.render_page(pdf, n, canvas, width);
			const unscaled = (await pdf.getPage(n)).getViewport({ scale: 1 });
			pages.push({ el: $page[0], canvas, scale: viewport.width / unscaled.width });
			bind_page(n - 1);
		}
		draw_boxes();
	}
	render_document();

	function submit() {
		if (!signers.length) return frappe.msgprint(__("Add at least one signer."));
		const unplaced = signers.find((s) => !s.sign_boxes.length);
		if (unplaced) {
			return frappe.msgprint(__("Place a signature box for {0} before sending.", [frappe.utils.escape_html(unplaced.signer_name)]));
		}
		// Freeze: rendering the PDF and mailing signers takes a while, and a
		// second click would send a duplicate request.
		frappe
			.call(
				request_name
					? {
							method: "frappe_sign.frappe_sign.api.update_signature_request",
							args: { request: request_name, signers: signers, sign_in_order: d.get_value("sign_in_order") },
							freeze: true,
							freeze_message: sending ? __("Sending for signature...") : __("Updating signature request..."),
					  }
					: {
							method: "frappe_sign.frappe_sign.api.create_signature_request",
							args: {
								reference_doctype: frm.doctype,
								reference_name: frm.doc.name,
								signers: signers,
								sign_in_order: d.get_value("sign_in_order"),
							},
							freeze: true,
							freeze_message: __("Sending for signature..."),
					  }
			)
			.then(() => {
				d.hide();
				frappe.show_alert({
					message: sending ? __("Signature requested") : __("Signature request updated"),
					indicator: "green",
				});
				frm.reload_doc();
			});
	}
};
