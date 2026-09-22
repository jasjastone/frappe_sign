frappe.pages["sign-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Sign"),
		single_column: true,
	});

	const $body = $(`
		<div class="sign-dashboard">
			<div class="mb-4">
				<h5>${__("Waiting for my signature")}</h5>
				<div class="sign-waiting"></div>
			</div>
			<div>
				<h5>${__("Documents I've sent")}</h5>
				<div class="sign-sent"></div>
			</div>
		</div>
	`).appendTo(page.main);

	page.set_primary_action(__("Refresh"), () => load());

	function card(inner, onclick) {
		return $(`<div class="widget" style="cursor:pointer">${inner}</div>`).on("click", onclick);
	}

	function empty(text) {
		return `<div class="text-muted">${text}</div>`;
	}

	function load() {
		frappe.xcall("frappe_sign.frappe_sign.api.get_dashboard_data").then((data) => {
			const $w = $body.find(".sign-waiting").empty();
			if (!data.waiting.length) {
				$w.html(empty(__("Nothing is waiting for your signature.")));
			}
			data.waiting.forEach((row) => {
				card(
					`<div class="widget-head"><div class="widget-title">${frappe.utils.escape_html(row.title)}</div></div>
					 <div class="widget-body"><span class="indicator-pill orange">${__("Awaiting Signature")}</span></div>`,
					() => frappe_sign.open_sign_dialog(row.access_token, null)
				).appendTo($w);
			});

			const $s = $body.find(".sign-sent").empty();
			if (!data.sent.length) {
				$s.html(empty(__("You haven't sent any documents for signature.")));
			}
			const colors = { Signed: "green", Rejected: "red", "Awaiting Signature": "orange", Draft: "gray" };
			data.sent.forEach((row) => {
				card(
					`<div class="widget-head"><div class="widget-title">${frappe.utils.escape_html(row.title)}</div></div>
					 <div class="widget-body">
						<span class="indicator-pill ${colors[row.status] || "gray"}">${__(row.status)}</span>
						<span class="text-muted ml-2">${row.signed || 0} / ${row.total} ${__("signed")}</span>
					 </div>`,
					() =>
						row.reference_doctype && row.reference_name
							? frappe.set_route("Form", row.reference_doctype, row.reference_name)
							: frappe.set_route("Form", "Signature Request", row.name)
				).appendTo($s);
			});
		});
	}

	load();
};
