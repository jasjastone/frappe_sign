/**
 * The ONE signing UI (D12). Mounted inside a frappe.ui.Dialog for User signers
 * (7.3) and inside the /sign-document guest page for everyone else (7.4).
 *
 * Usage:
 *   frappe_sign.mount_sign_widget(container_el, token, { on_done: (status) => {} });
 */
window.frappe_sign = window.frappe_sign || {};

(function () {
	const PDFJS_SRC = "/assets/frappe_sign/js/lib/pdf.min.js";
	const PDFJS_WORKER = "/assets/frappe_sign/js/lib/pdf.worker.min.js";
	const SIGPAD_SRC = "/assets/frappe_sign/js/lib/signature_pad.min.js";

	function load_script(src) {
		return new Promise((resolve, reject) => {
			if (document.querySelector(`script[src="${src}"]`)) return resolve();
			const el = document.createElement("script");
			el.src = src;
			el.onload = resolve;
			el.onerror = () => reject(new Error(`Failed to load ${src}`));
			document.head.appendChild(el);
		});
	}

	async function load_libs() {
		await Promise.all([load_script(PDFJS_SRC), load_script(SIGPAD_SRC)]);
		window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
	}
	frappe_sign.load_libs = load_libs;

	/**
	 * Render one PDF page into a canvas, `width` CSS pixels wide. Returns the
	 * CSS-pixel viewport. `ratio` > 1 draws that many device pixels per CSS pixel,
	 * so text stays sharp when a phone pinch-zooms (the placement dialog, which
	 * maps pointer pixels 1:1 onto the canvas, leaves it at 1).
	 */
	async function render_page(pdf, page_no, canvas, width, ratio) {
		const page = await pdf.getPage(page_no);
		const scale = width / page.getViewport({ scale: 1 }).width;
		const viewport = page.getViewport({ scale });
		const pixels = page.getViewport({ scale: scale * (ratio || 1) });
		canvas.width = pixels.width;
		canvas.height = pixels.height;
		canvas.style.width = viewport.width + "px";
		canvas.style.height = viewport.height + "px";
		await page.render({ canvasContext: canvas.getContext("2d"), viewport: pixels }).promise;
		return viewport;
	}
	frappe_sign.render_page = render_page;

	/**
	 * Plain fetch against the whitelisted API — the desk's frappe.call is not
	 * loaded on website pages, and this widget has to work on both (D12).
	 */
	async function call(method, args) {
		const res = await fetch(`/api/method/frappe_sign.frappe_sign.api.${method}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": frappe.csrf_token || "",
			},
			body: JSON.stringify(args),
		});
		const data = await res.json();
		if (!res.ok) {
			const messages = JSON.parse(data._server_messages || "[]").map((m) => JSON.parse(m).message);
			throw new Error(messages.join(" ") || data.exception || __("Something went wrong."));
		}
		return data.message;
	}
	frappe_sign.call = call;

	/** Draw an image source onto a canvas, crop to the ink, return a PNG data URL (or null if blank). */
	function trimmed_png(source, w, h) {
		const c = document.createElement("canvas");
		c.width = w;
		c.height = h;
		const g = c.getContext("2d");
		g.drawImage(source, 0, 0, w, h);
		const px = g.getImageData(0, 0, w, h).data;
		let x0 = w,
			y0 = h,
			x1 = -1,
			y1 = -1;
		for (let y = 0; y < h; y++) {
			for (let x = 0; x < w; x++) {
				if (px[(y * w + x) * 4 + 3] > 10) {
					if (x < x0) x0 = x;
					if (x > x1) x1 = x;
					if (y < y0) y0 = y;
					if (y > y1) y1 = y;
				}
			}
		}
		if (x1 < 0) return null;
		const pad = 4;
		x0 = Math.max(0, x0 - pad);
		y0 = Math.max(0, y0 - pad);
		x1 = Math.min(w - 1, x1 + pad);
		y1 = Math.min(h - 1, y1 + pad);
		const out = document.createElement("canvas");
		out.width = x1 - x0 + 1;
		out.height = y1 - y0 + 1;
		out.getContext("2d").drawImage(c, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
		return out.toDataURL("image/png");
	}

	function load_image(src) {
		return new Promise((resolve, reject) => {
			const img = new Image();
			img.onload = () => resolve(img);
			img.onerror = () => reject(new Error(__("Could not read that image.")));
			img.src = src;
		});
	}

	frappe_sign.mount_sign_widget = async function (container, token, opts) {
		opts = opts || {};
		const $c = $(container).empty().addClass("frappe-sign-widget");
		$c.html(`<div class="text-muted">${__("Loading document...")}</div>`);

		await load_libs();

		let ctx;
		try {
			ctx = await call("get_signing_context", { key: token });
		} catch (e) {
			$c.html(`<div class="text-danger">${frappe.utils.escape_html(e.message)}</div>`);
			return;
		}

		const title = frappe.utils.escape_html(ctx.request_title || "");
		$c.html(`
			<div class="sign-doc-head">
				<div class="sign-doc-title">${title}</div>
				<a class="small" href="${ctx.pdf_url}" target="_blank" rel="noopener">${__("Open full PDF")}</a>
			</div>
			<div class="sign-places text-muted small">
				${
					ctx.sign_boxes.length > 1
						? __("You sign in {0} places. One signature fills all of them.", [ctx.sign_boxes.length])
						: __("Read the document, then sign in the highlighted box.")
				}
				<button type="button" class="sign-show-where">↓ ${__("Show where to sign")}</button>
			</div>
			<div class="sign-pdf-pages"></div>
			<div class="sign-pad-section">
				<div class="sign-label">${__("Your signature")}</div>
				<div class="sign-saved" hidden>
					<img class="sign-saved-img" />
					<button type="button" class="btn btn-xs btn-default sign-change">${__("Change")}</button>
				</div>
				<div class="sign-new">
					<div class="sign-tabs btn-group btn-group-sm" role="group">
						<button type="button" class="btn btn-default" data-mode="draw">${__("Draw")}</button>
						<button type="button" class="btn btn-default" data-mode="upload">${__("Upload")}</button>
					</div>
					<div class="sign-pane" data-pane="draw" hidden>
						<canvas class="sign-pad-canvas"></canvas>
						<button type="button" class="btn btn-xs btn-default sign-clear">${__("Clear")}</button>
					</div>
					<div class="sign-pane" data-pane="upload" hidden>
						<input type="file" class="sign-upload-input" accept="image/*" />
						<img class="sign-upload-preview" hidden />
					</div>
				</div>
			</div>
			<div class="sign-reject-panel" hidden>
				<textarea class="form-control sign-reject-reason" rows="2" placeholder="${__("Why are you declining?")}"></textarea>
				<button type="button" class="btn btn-sm btn-danger sign-reject-confirm">${__("Confirm decline")}</button>
			</div>
			<div class="sign-error text-danger" hidden></div>
			<div class="sign-bar">
				<div class="sign-consent small text-muted">${__(
					"By clicking Accept & Sign, I agree this is my electronic signature on {0}. We'll remember it for your next document.",
					[`<b>${title}</b>`]
				)}</div>
				<div class="sign-actions">
					<button type="button" class="btn btn-default sign-reject">${__("Decline")}</button>
					<button type="button" class="btn btn-primary sign-submit"></button>
				</div>
			</div>
		`);

		// --- whole document, flowing with the page (no inner scroll box, so a phone
		// scrolls and pinch-zooms it naturally), with every box this signer signs in.
		const $pages = $c.find(".sign-pdf-pages");
		const pdf = await window.pdfjsLib.getDocument(ctx.pdf_url).promise;
		const width = Math.min(($c.width() || 640) - 4, 640);
		// Sharp when zoomed, capped at 2x to spare old devices' memory.
		const ratio = Math.min(Math.max(window.devicePixelRatio || 1, 1), 2);
		for (let n = 1; n <= pdf.numPages; n++) {
			const $page = $(`<div class="sign-pdf-page"><canvas></canvas></div>`).appendTo($pages);
			const canvas = $page.find("canvas")[0];
			const viewport = await render_page(pdf, n, canvas, width, ratio);
			const scale = viewport.width / (await pdf.getPage(n)).getViewport({ scale: 1 }).width;
			ctx.sign_boxes
				.filter((b) => b.page === n - 1)
				.forEach((b) =>
					$(`<div class="sign-pdf-box"><span class="sign-here">${__("Sign here")}</span><img hidden /></div>`)
						.css({ left: b.x * scale + "px", top: b.y * scale + "px", width: b.w * scale + "px", height: b.h * scale + "px" })
						.appendTo($page)
				);
		}
		const $box = $pages.find(".sign-pdf-box"); // every place, previewed together
		const first_box = $box.toArray().sort(
			(a, b) => a.parentNode.offsetTop + a.offsetTop - (b.parentNode.offsetTop + b.offsetTop)
		)[0];
		const go = (el) => el && el.scrollIntoView({ behavior: "smooth", block: "center" });
		const go_to_pad = () => go($c.find(".sign-pad-section")[0]);

		// Tapping a box takes you to where you make the signature — never signs by
		// itself, so a stray tap while scrolling can't sign a contract.
		$box.on("click", go_to_pad);
		$c.find(".sign-show-where").on("click", () => go(first_box));

		// --- signature capture -------------------------------------------------
		let image = null; // trimmed PNG data URL of whatever will be stamped
		let mode = null;
		let pad = null;
		let uploaded = null;

		// The bar's main button is the next step: make a signature, then sign.
		function set_image(src) {
			image = src;
			$box.toggleClass("has-image", !!src).find("img").attr("src", src || "").prop("hidden", !src);
			$c.find(".sign-submit").text(src ? __("Accept & Sign") : __("Add Signature"));
			$c.find(".sign-consent").prop("hidden", !src);
		}

		function pad_image() {
			if (!pad || pad.isEmpty()) return null;
			const c = pad.canvas;
			return trimmed_png(c, c.width, c.height);
		}

		function set_mode(next) {
			mode = next;
			$c.find(".sign-tabs .btn").removeClass("btn-primary").filter(`[data-mode="${next}"]`).addClass("btn-primary");
			$c.find(".sign-pane").each((_i, el) => {
				el.hidden = $(el).data("pane") !== next;
			});
			if (next === "draw" && !pad) {
				// Size the backing store to the rendered size — signature_pad does
				// not correct for CSS scaling, so a shrunk canvas mis-draws on phones.
				const canvas = $c.find(".sign-pad-canvas")[0];
				const ratio = Math.max(window.devicePixelRatio || 1, 1);
				canvas.width = canvas.offsetWidth * ratio;
				canvas.height = canvas.offsetHeight * ratio;
				canvas.getContext("2d").scale(ratio, ratio);
				pad = new window.SignaturePad(canvas, { backgroundColor: "rgba(255,255,255,0)" });
				pad.addEventListener("endStroke", () => set_image(pad_image()));
			}
			set_image(next === "draw" ? pad_image() : uploaded);
		}

		function show_new() {
			$c.find(".sign-saved").prop("hidden", true);
			$c.find(".sign-new").prop("hidden", false);
			set_mode("draw");
		}

		$c.find(".sign-tabs .btn").on("click", (e) => set_mode($(e.currentTarget).data("mode")));
		$c.find(".sign-clear").on("click", () => {
			pad && pad.clear();
			set_image(null);
		});
		$c.find(".sign-change").on("click", show_new);
		$c.find(".sign-upload-input").on("change", (e) => {
			const file = e.target.files[0];
			if (!file) return;
			const reader = new FileReader();
			reader.onload = async () => {
				try {
					// Through a canvas: always PNG, and cropped like a drawn one.
					const img = await load_image(reader.result);
					uploaded = trimmed_png(img, img.naturalWidth, img.naturalHeight) || reader.result;
					$c.find(".sign-upload-preview").attr("src", uploaded).prop("hidden", false);
					set_image(uploaded);
				} catch (err) {
					show_error(err.message);
				}
			};
			reader.readAsDataURL(file);
		});

		if (ctx.saved_signature) {
			$c.find(".sign-new").prop("hidden", true);
			$c.find(".sign-saved").prop("hidden", false).find("img").attr("src", ctx.saved_signature);
			set_image(ctx.saved_signature);
		} else {
			show_new();
		}

		function show_error(msg) {
			$c.find(".sign-error").text(msg).prop("hidden", false);
			go($c.find(".sign-error")[0]);
		}

		function finish(status) {
			if (opts.on_done) opts.on_done(status);
		}

		// --- actions ------------------------------------------------------------
		$c.find(".sign-submit").on("click", async function () {
			const $btn = $(this);
			$c.find(".sign-error").prop("hidden", true);
			if (!image) return go_to_pad();
			$btn.prop("disabled", true);
			try {
				await call("submit_signature", {
					key: token,
					image_base64: image,
					is_upload: mode === "upload" ? 1 : 0,
				});
				finish("Signed");
			} catch (e) {
				$btn.prop("disabled", false);
				show_error(e.message);
			}
		});

		// Inline reason panel rather than a dialog — frappe.ui.Dialog is desk-only.
		$c.find(".sign-reject").on("click", () => {
			$c.find(".sign-reject-panel").prop("hidden", false);
			go($c.find(".sign-reject-panel")[0]);
			$c.find(".sign-reject-reason").trigger("focus");
		});
		$c.find(".sign-reject-confirm").on("click", async function () {
			const reason = $c.find(".sign-reject-reason").val().trim();
			if (!reason) return show_error(__("A reason is required to decline."));
			$(this).prop("disabled", true);
			try {
				await call("reject_signature", { key: token, reason });
				finish("Rejected");
			} catch (e) {
				$(this).prop("disabled", false);
				show_error(e.message);
			}
		});
	};
})();
