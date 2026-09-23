// Number cards on top (what needs me, what is out, what is done); the card
// you pick lists its documents below, one line each.
frappe.pages["sign-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Sign"), single_column: true });
	page.set_primary_action(__("Refresh"), () => load());

	const $body = $(`<div class="sign-dash">
			<div class="sign-dash-cards"></div>
			<div class="sign-dash-list frappe-card"></div>
		</div>`).appendTo(page.main);
	const esc = frappe.utils.escape_html;
	const colors = { Signed: "green", Rejected: "red", "Awaiting Signature": "orange" };
	let data = null;
	let current = null;

	const CARDS = [
		{ key: "waiting", label: __("Waiting for my signature"), color: "orange",
			rows: () => data.waiting, empty: __("Nothing is waiting for your signature.") },
		{ key: "out", label: __("Out for signature"), color: "blue",
			rows: () => data.sent.filter((r) => r.status === "Awaiting Signature"), empty: __("Nothing you sent is waiting on anyone.") },
		{ key: "signed", label: __("Signed"), color: "green",
			rows: () => data.sent.filter((r) => r.status === "Signed"), empty: __("Nothing you sent has been signed yet.") },
		{ key: "declined", label: __("Declined"), color: "red",
			rows: () => data.sent.filter((r) => r.status === "Rejected"), empty: __("Nothing you sent has been declined.") },
	];

	function row_html(card, r) {
		const ref = r.reference_name ? `${__(r.reference_doctype)} ${esc(r.reference_name)}` : esc(r.request || r.name);
		const right =
			card.key === "waiting"
				? `<button class="btn btn-xs btn-primary">${__("Sign")}</button>`
				: `<span class="text-muted small">${__("{0} of {1} signed", [r.signed || 0, r.total])}</span>
				   <span class="indicator-pill ${colors[r.status] || "gray"}">${__(r.status === "Rejected" ? "Declined" : r.status)}</span>`;
		return `<div class="sign-dash-row">
				<div class="sign-dash-main">
					<div class="ellipsis">${esc(r.title || "")}</div>
					<div class="text-muted small ellipsis">${ref}${r.since ? " · " + frappe.datetime.comment_when(r.since) : ""}</div>
				</div>
				<div class="sign-dash-right">${right}</div>
			</div>`;
	}

	function open(card, r) {
		if (card.key === "waiting") {
			frappe_sign.open_sign_dialog(r.access_token, null, () => load());
		} else if (r.reference_doctype && r.reference_name) {
			frappe.set_route("Form", r.reference_doctype, r.reference_name);
		} else {
			frappe.set_route("Form", "Signature Request", r.name);
		}
	}

	function render() {
		const $cards = $body.find(".sign-dash-cards").empty();
		CARDS.forEach((card) => {
			$(`<div class="sign-dash-card ${card === current ? "is-active" : ""}" style="--c: var(--${card.color}-500)">
					<div class="sign-dash-number">${card.rows().length}</div>
					<div class="sign-dash-label">${card.label}</div>
				</div>`)
				.on("click", () => {
					current = card;
					render();
				})
				.appendTo($cards);
		});
		const rows = current.rows();
		const $list = $body.find(".sign-dash-list").html(
			`<div class="sign-dash-list-head">${current.label}</div>` +
				(rows.length ? rows.map((r) => row_html(current, r)).join("") : `<div class="sign-dash-empty text-muted">${current.empty}</div>`)
		);
		$list.find(".sign-dash-row").each((i, el) => $(el).on("click", () => open(current, rows[i])));
	}

	function load() {
		frappe.xcall("frappe_sign.frappe_sign.api.get_dashboard_data").then((d) => {
			data = d;
			// Start on what needs doing: my signatures first, else what I'm waiting on.
			current = current || (data.waiting.length ? CARDS[0] : CARDS[1]);
			render();
		});
	}

	load();
};
