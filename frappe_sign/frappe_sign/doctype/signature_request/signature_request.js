// Copyright (c) 2026, jasjastone and contributors
// For license information, please see license.txt

// A request for a record is managed from that record. A standalone one (an
// uploaded letter, contract, office document) is managed here: add the PDF(s),
// save, then Request Signature.
frappe.ui.form.on("Signature Request", {
	refresh(frm) {
		// The field's own Attach button becomes "Add PDFs": one file attaches as
		// before, several are sorted and merged into one document first.
		const field = frm.fields_dict.source_pdf;
		field.$input.html(__("Add PDFs"));
		field.on_attach_click = () => pick_pdfs((files) => add_pdfs(frm, files));

		if (frm.is_new()) return;
		if (frm.doc.status !== "Draft") frm.disable_save();
		if (frm.doc.source_pdf) {
			frm.add_custom_button(__("Preview PDF"), () => frappe_sign.preview_pdf(frm.doc.name));
		}
		if (frm.doc.reference_doctype || !frm.perm[0]?.write) return;

		const config = { allow_external_signers: 1 };
		if (frm.doc.status === "Draft") {
			frm.page.set_primary_action(__("Request Signature"), () =>
				frappe_sign.open_request_dialog(frm, config, frm.doc.name)
			);
		} else if (frm.doc.status === "Awaiting Signature") {
			if (frm.doc.signers.every((s) => s.status === "Pending")) {
				frm.add_custom_button(__("Update Signature Request"), () =>
					frappe_sign.open_request_dialog(frm, config, frm.doc.name)
				);
			}
			frm.add_custom_button(__("Withdraw Request"), () => frappe_sign.withdraw(frm, frm.doc));
			frm.add_custom_button(__("Send Reminder"), () => frappe_sign.send_reminder(frm.doc.name));
		}
	},
});

const is_pdf = (f) => f.type === "application/pdf" || /\.pdf$/i.test(f.name);

/** The browser's file picker, PDFs only; refuses anything else with a message. */
function pick_pdfs(on_pick) {
	$('<input type="file" accept=".pdf,application/pdf" multiple>')
		.on("change", (e) => {
			const files = [...e.target.files];
			const refused = files.filter((f) => !is_pdf(f));
			if (refused.length) {
				frappe.msgprint({
					title: __("Only PDF files"),
					indicator: "orange",
					message: __("{0} can't be added: only PDF files are supported for now. Save Word or other documents as PDF first.", [
						refused.map((f) => frappe.utils.escape_html(f.name)).join(", "),
					]),
				});
			}
			const pdfs = files.filter(is_pdf);
			if (pdfs.length) on_pick(pdfs);
		})
		.trigger("click");
}

async function upload(file, frm) {
	const fd = new FormData();
	fd.append("file", file, file.name);
	fd.append("is_private", 1);
	if (frm && !frm.is_new()) {
		fd.append("doctype", frm.doctype);
		fd.append("docname", frm.doc.name);
		fd.append("fieldname", "source_pdf");
	}
	const res = await fetch("/api/method/upload_file", {
		method: "POST",
		body: fd,
		headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
	});
	const data = await res.json();
	if (!res.ok) {
		const messages = JSON.parse(data._server_messages || "[]").map((m) => JSON.parse(m).message);
		frappe.msgprint(messages.join("<br>") || __("Could not upload {0}.", [frappe.utils.escape_html(file.name)]));
		throw new Error(file.name);
	}
	return data.message;
}

function add_pdfs(frm, files) {
	if (files.length > 1) return sort_dialog(frm, files);
	frappe.dom.freeze(__("Uploading..."));
	upload(files[0], frm)
		.then((file) => {
			frm.set_value("source_pdf", file.file_url);
			if (!frm.is_new()) frm.attachments.update_attachment(file);
		})
		.finally(() => frappe.dom.unfreeze());
}

/** Step 1: put the files in order (drag), drop any (×), add more (+). */
function sort_dialog(frm, files) {
	const d = new frappe.ui.Dialog({
		title: __("Merge PDFs"),
		fields: [{ fieldname: "list", fieldtype: "HTML" }],
		primary_action_label: __("Preview"),
		primary_action: () => {
			d.hide();
			preview_dialog(frm, files, () => sort_dialog(frm, files));
		},
	});
	const $list = $(d.fields_dict.list.wrapper);

	function render() {
		$list.html(`
			<div class="sign-merge-head">
				<span class="text-muted">${__("Drag to put the documents in order. They are joined top to bottom.")}</span>
				<button class="btn btn-sm btn-default sign-merge-add" title="${__("Add PDFs")}">+</button>
			</div>
			<div class="sign-merge-list">${files
				.map(
					(f, i) => `<div class="sign-merge-item" draggable="true" data-i="${i}">
						<span class="sign-merge-grip">⋮⋮</span>
						<span class="sign-merge-no">${i + 1}.</span>
						<span class="sign-merge-name ellipsis">${frappe.utils.escape_html(f.name)}</span>
						<a class="sign-merge-remove" title="${__("Remove")}">&times;</a>
					</div>`
				)
				.join("")}</div>`);
		d.get_primary_btn().prop("disabled", !files.length);

		let from = null;
		$list.find(".sign-merge-item")
			.on("dragstart", (e) => (from = +e.currentTarget.dataset.i))
			.on("dragover", (e) => e.preventDefault())
			.on("drop", (e) => {
				e.preventDefault();
				const to = +e.currentTarget.dataset.i;
				if (from === null || from === to) return;
				files.splice(to, 0, files.splice(from, 1)[0]);
				render();
			});
		$list.find(".sign-merge-remove").on("click", (e) => {
			files.splice(+$(e.currentTarget).closest(".sign-merge-item").data("i"), 1);
			render();
		});
		$list.find(".sign-merge-add").on("click", () =>
			pick_pdfs((more) => {
				files.push(...more);
				render();
			})
		);
	}
	render();
	d.show();
}

/**
 * Step 2: the merged document, rendered from the files in the browser — nothing
 * is uploaded until Attach. Attach saves one merged PDF as the Document to Sign.
 */
async function preview_dialog(frm, files, back) {
	await frappe_sign.load_libs();
	const d = new frappe.ui.Dialog({
		title: __("Merged document ({0} files)", [files.length]),
		size: "extra-large",
		fields: [{ fieldname: "pages", fieldtype: "HTML" }],
		primary_action_label: __("Attach"),
		primary_action: attach,
		secondary_action_label: __("Back"),
		secondary_action: () => {
			d.hide();
			back();
		},
	});
	d.show();
	const $wrap = $(`<div class="sign-place-wrap sign-merge-preview"></div>`).appendTo(d.fields_dict.pages.wrapper);
	for (let i = 0; !$wrap.width() && i < 60; i++) await new Promise(requestAnimationFrame);
	const width = Math.min($wrap.width() - 20, 760);

	for (const file of files) {
		let pdf;
		try {
			pdf = await window.pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
		} catch (e) {
			d.hide();
			frappe.msgprint(__("{0} could not be read as a PDF. Remove it and try again.", [frappe.utils.escape_html(file.name)]));
			return back();
		}
		for (let n = 1; n <= pdf.numPages; n++) {
			const canvas = $(`<div class="sign-place-page"><canvas></canvas></div>`).appendTo($wrap).find("canvas")[0];
			await frappe_sign.render_page(pdf, n, canvas, width);
		}
	}

	async function attach() {
		frappe.dom.freeze(__("Merging PDFs..."));
		try {
			const urls = [];
			for (const file of files) urls.push((await upload(file)).file_url);
			const url =
				urls.length > 1 ? await frappe.xcall("frappe_sign.frappe_sign.api.merge_pdfs", { file_urls: urls }) : urls[0];
			d.hide();
			frm.set_value("source_pdf", url);
		} finally {
			frappe.dom.unfreeze();
		}
	}
}
