(() => {
  var __defProp = Object.defineProperty;
  var __defProps = Object.defineProperties;
  var __getOwnPropDescs = Object.getOwnPropertyDescriptors;
  var __getOwnPropSymbols = Object.getOwnPropertySymbols;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __propIsEnum = Object.prototype.propertyIsEnumerable;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __spreadValues = (a, b) => {
    for (var prop in b || (b = {}))
      if (__hasOwnProp.call(b, prop))
        __defNormalProp(a, prop, b[prop]);
    if (__getOwnPropSymbols)
      for (var prop of __getOwnPropSymbols(b)) {
        if (__propIsEnum.call(b, prop))
          __defNormalProp(a, prop, b[prop]);
      }
    return a;
  };
  var __spreadProps = (a, b) => __defProps(a, __getOwnPropDescs(b));

  // ../frappe_sign/frappe_sign/public/js/sign_widget.js
  window.frappe_sign = window.frappe_sign || {};
  (function() {
    const PDFJS_SRC = "/assets/frappe_sign/js/lib/pdf.min.js";
    const PDFJS_WORKER = "/assets/frappe_sign/js/lib/pdf.worker.min.js";
    const SIGPAD_SRC = "/assets/frappe_sign/js/lib/signature_pad.min.js";
    function load_script(src) {
      return new Promise((resolve, reject) => {
        if (document.querySelector(`script[src="${src}"]`))
          return resolve();
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
    async function call(method, args) {
      const res = await fetch(`/api/method/frappe_sign.frappe_sign.api.${method}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Frappe-CSRF-Token": frappe.csrf_token || ""
        },
        body: JSON.stringify(args)
      });
      const data = await res.json();
      if (!res.ok) {
        const messages = JSON.parse(data._server_messages || "[]").map((m) => JSON.parse(m).message);
        throw new Error(messages.join(" ") || data.exception || __("Something went wrong."));
      }
      return data.message;
    }
    frappe_sign.call = call;
    function trimmed_png(source, w, h) {
      const c = document.createElement("canvas");
      c.width = w;
      c.height = h;
      const g = c.getContext("2d");
      g.drawImage(source, 0, 0, w, h);
      const px = g.getImageData(0, 0, w, h).data;
      let x0 = w, y0 = h, x1 = -1, y1 = -1;
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          if (px[(y * w + x) * 4 + 3] > 10) {
            if (x < x0)
              x0 = x;
            if (x > x1)
              x1 = x;
            if (y < y0)
              y0 = y;
            if (y > y1)
              y1 = y;
          }
        }
      }
      if (x1 < 0)
        return null;
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
    frappe_sign.mount_sign_widget = async function(container, token, opts) {
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
				${ctx.sign_boxes.length > 1 ? __("You sign in {0} places. One signature fills all of them.", [ctx.sign_boxes.length]) : __("Read the document, then sign in the highlighted box.")}
				<a class="sign-show-where">${__("Show where")}</a>
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
      const $pages = $c.find(".sign-pdf-pages");
      const pdf = await window.pdfjsLib.getDocument(ctx.pdf_url).promise;
      const width = Math.min(($c.width() || 640) - 4, 640);
      const ratio = Math.min(Math.max(window.devicePixelRatio || 1, 1), 2);
      for (let n = 1; n <= pdf.numPages; n++) {
        const $page = $(`<div class="sign-pdf-page"><canvas></canvas></div>`).appendTo($pages);
        const canvas = $page.find("canvas")[0];
        const viewport = await render_page(pdf, n, canvas, width, ratio);
        const scale = viewport.width / (await pdf.getPage(n)).getViewport({ scale: 1 }).width;
        ctx.sign_boxes.filter((b) => b.page === n - 1).forEach(
          (b) => $(`<div class="sign-pdf-box"><span class="sign-here">${__("Sign here")}</span><img hidden /></div>`).css({ left: b.x * scale + "px", top: b.y * scale + "px", width: b.w * scale + "px", height: b.h * scale + "px" }).appendTo($page)
        );
      }
      const $box = $pages.find(".sign-pdf-box");
      const first_box = $box.toArray().sort(
        (a, b) => a.parentNode.offsetTop + a.offsetTop - (b.parentNode.offsetTop + b.offsetTop)
      )[0];
      const go = (el) => el && el.scrollIntoView({ behavior: "smooth", block: "center" });
      const go_to_pad = () => go($c.find(".sign-pad-section")[0]);
      $box.on("click", go_to_pad);
      $c.find(".sign-show-where").on("click", () => go(first_box));
      let image = null;
      let mode = null;
      let pad = null;
      let uploaded = null;
      function set_image(src) {
        image = src;
        $box.toggleClass("has-image", !!src).find("img").attr("src", src || "").prop("hidden", !src);
        $c.find(".sign-submit").text(src ? __("Accept & Sign") : __("Add Signature"));
        $c.find(".sign-consent").prop("hidden", !src);
      }
      function pad_image() {
        if (!pad || pad.isEmpty())
          return null;
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
          const canvas = $c.find(".sign-pad-canvas")[0];
          const ratio2 = Math.max(window.devicePixelRatio || 1, 1);
          canvas.width = canvas.offsetWidth * ratio2;
          canvas.height = canvas.offsetHeight * ratio2;
          canvas.getContext("2d").scale(ratio2, ratio2);
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
        if (!file)
          return;
        const reader = new FileReader();
        reader.onload = async () => {
          try {
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
        if (opts.on_done)
          opts.on_done(status);
      }
      $c.find(".sign-submit").on("click", async function() {
        const $btn = $(this);
        $c.find(".sign-error").prop("hidden", true);
        if (!image)
          return go_to_pad();
        $btn.prop("disabled", true);
        try {
          await call("submit_signature", {
            key: token,
            image_base64: image,
            is_upload: mode === "upload" ? 1 : 0
          });
          finish("Signed");
        } catch (e) {
          $btn.prop("disabled", false);
          show_error(e.message);
        }
      });
      $c.find(".sign-reject").on("click", () => {
        $c.find(".sign-reject-panel").prop("hidden", false);
        go($c.find(".sign-reject-panel")[0]);
        $c.find(".sign-reject-reason").trigger("focus");
      });
      $c.find(".sign-reject-confirm").on("click", async function() {
        const reason = $c.find(".sign-reject-reason").val().trim();
        if (!reason)
          return show_error(__("A reason is required to decline."));
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

  // ../frappe_sign/frappe_sign/public/js/signature_button.js
  frappe.provide("frappe_sign");
  frappe_sign.signable_config = (doctype) => (frappe.boot.frappe_sign || {})[doctype];
  frappe_sign.is_gated = (frm, config) => config.require_signature_to_submit && frm.meta.is_submittable && frm.doc.docstatus === 0 && !frm.is_dirty();
  var SIGN_INDICATORS = {
    "Awaiting Signature": [__("Awaiting Signature"), "orange"],
    Signed: [__("Signed"), "green"],
    Rejected: [__("Signature Declined"), "red"]
  };
  var core_get_indicator = frappe.get_indicator;
  frappe.get_indicator = function(doc, doctype, ...rest) {
    const dt = doctype || doc.doctype;
    const ind = doc.docstatus === 0 && !doc.__unsaved && frappe_sign.signable_config(dt) && SIGN_INDICATORS[doc.signature_status];
    return ind ? [...ind, `signature_status,=,${doc.signature_status}`] : core_get_indicator.call(this, doc, doctype, ...rest);
  };
  var core_set_fields = frappe.views.ListView.prototype.set_fields;
  frappe.views.ListView.prototype.set_fields = async function() {
    await core_set_fields.call(this);
    if (frappe_sign.signable_config(this.doctype))
      this._add_field("signature_status");
  };
  var toolbar_status = frappe.ui.form.Toolbar.prototype.get_action_status;
  frappe.ui.form.Toolbar.prototype.get_action_status = function() {
    const status = toolbar_status.call(this);
    const config = status === "Submit" && frappe_sign.signable_config(this.frm.doctype);
    return config && frappe_sign.is_gated(this.frm, config) ? null : status;
  };
  frappe.ui.form.on("*", {
    refresh(frm) {
      const config = frappe_sign.signable_config(frm.doctype);
      if (!config || frm.is_new())
        return;
      frappe.xcall("frappe_sign.frappe_sign.api.get_signature_status", {
        reference_doctype: frm.doctype,
        reference_name: frm.doc.name
      }).then((status) => {
        if (status)
          frappe_sign.render_signers(frm, status);
        frappe_sign.set_sign_actions(frm, config, status);
      });
    }
  });
  frappe_sign.set_sign_actions = function(frm, config, status) {
    var _a;
    const sign = () => frappe_sign.open_sign_dialog(status.my_token, frm);
    const request = () => frappe_sign.open_request_dialog(frm, config);
    const gated = frappe_sign.is_gated(frm, config);
    const can_write = (_a = frm.perm[0]) == null ? void 0 : _a.write;
    const draft = frm.doc.docstatus === 0;
    const needs_request = !status || ["Rejected", "Withdrawn"].includes(status.status);
    const out = draft && status && (status.status === "Awaiting Signature" || status.status === "Signed" && frm.meta.is_submittable);
    const untouched = status && status.status === "Awaiting Signature" && status.signers.every((s) => s.status === "Pending");
    const can_request = can_write && (draft || !config.require_signature_to_submit);
    if (out)
      frappe_sign.lock_form(frm);
    if (can_write && untouched) {
      frm.add_custom_button(
        __("Update Signature Request"),
        () => frappe_sign.open_request_dialog(frm, config, status.name)
      );
    }
    if (can_write && out)
      frm.add_custom_button(__("Withdraw Request"), () => frappe_sign.withdraw(frm, status));
    if (can_write && status && status.status === "Awaiting Signature") {
      frm.add_custom_button(__("Send Reminder"), () => frappe_sign.send_reminder(status.name));
    }
    if (can_request && needs_request && !gated) {
      frm.add_custom_button(__("Request Signature"), request);
    }
    if (out) {
      frm.dashboard.clear_comment();
      frm.dashboard.add_comment(
        __("This document is out for signature, so it can't be edited. Withdraw the request to edit it."),
        "orange",
        true
      );
    } else if (gated) {
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
      frm.page.set_primary_action(__("Submit"), () => frm.savesubmit());
    } else {
      const signed = status.signers.filter((s) => s.status === "Signed").length;
      frm.page.set_primary_action(
        __("Awaiting Signatures ({0}/{1})", [signed, status.signers.length]),
        () => {
          var _a2;
          return (_a2 = frm.layout.wrapper.find(".frappe-sign-status-section")[0]) == null ? void 0 : _a2.scrollIntoView({ behavior: "smooth" });
        }
      );
    }
  };
  frappe_sign.lock_form = function(frm) {
    frm.perm = frm.perm.map((p) => __spreadProps(__spreadValues({}, p), { write: 0 }));
    frm.refresh_fields();
  };
  frappe_sign.send_reminder = function(request) {
    frappe.xcall("frappe_sign.frappe_sign.api.send_reminder", { request }).then(
      (names) => frappe.show_alert({ message: __("Reminder sent to {0}", [names.join(", ")]), indicator: "green" })
    );
  };
  frappe_sign.withdraw = function(frm, status) {
    const signed = status.signers.filter((s) => s.status === "Signed").length;
    const msg = signed ? __("Withdraw {0}? The {1} signature(s) already given will be discarded, and you can edit the document again.", [status.name, signed]) : __("Withdraw {0}? Signers' links will stop working, and you can edit the document again.", [status.name]);
    frappe.confirm(
      msg,
      () => frappe.xcall("frappe_sign.frappe_sign.api.withdraw_signature_request", { request: status.name }).then(() => {
        frappe.show_alert({ message: __("Signature request withdrawn"), indicator: "orange" });
        frm.reload_doc();
      })
    );
  };
  frappe_sign.render_signers = function(frm, status) {
    const colors = { Signed: "green", Rejected: "red", Pending: "orange", "Awaiting Signature": "orange" };
    const pill = (s) => `<span class="indicator-pill ${colors[s] || "gray"}">${__(s)}</span>`;
    const esc = frappe.utils.escape_html;
    const rows = status.signers.map(
      (s, i) => `<tr>
				<td>${status.sign_in_order ? `${i + 1}. ` : ""}${esc(s.signer_name)}<div class="text-muted small">${esc(s.signer_email)}</div></td>
				<td>${__(s.signer_type)}</td>
				<td>${pill(s.status)}</td>
				<td>${s.status === "Signed" ? frappe.datetime.str_to_user(s.signed_on) : s.status === "Rejected" ? `<span class="text-danger">${esc(s.rejection_reason || "")}</span>` : `<span class="text-muted">${s.turn ? __("Waiting for signature") : __("Waiting for their turn")}</span>`}</td>
			</tr>`
    ).join("");
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
			${status.earlier_requests ? `<div class="text-muted small mt-2">${__("{0} earlier request(s) on this document.", [status.earlier_requests])}
						<a href="/app/signature-request?reference_doctype=${encodeURIComponent(frm.doctype)}&reference_name=${encodeURIComponent(frm.doc.name)}">${__("View all")}</a></div>` : ""}
		</div>`;
    frm.layout.wrapper.find(".frappe-sign-status-section").remove();
    const tab = frm.layout.tabs.find((t) => !t.is_hidden());
    const $section = $(`<div class="form-dashboard-section card-section frappe-sign-status-section">
			<div class="section-head">${__("Signers")}</div>
			<div class="section-body">${html}</div>
		</div>`).prependTo(tab ? tab.wrapper : frm.layout.wrapper);
    $section.find(".sign-preview").on("click", () => frappe_sign.preview_pdf(status.name));
  };
  frappe_sign.request_pdf_url = function(request, download) {
    return `/api/method/frappe_sign.frappe_sign.api.get_request_pdf?request=${encodeURIComponent(request)}` + (download ? "&download=1" : "");
  };
  frappe_sign.preview_pdf = function(request) {
    const d = new frappe.ui.Dialog({
      title: request,
      size: "extra-large",
      primary_action_label: __("Download"),
      primary_action: () => window.open(frappe_sign.request_pdf_url(request, 1))
    });
    $(`<iframe class="sign-preview-frame" src="${frappe_sign.request_pdf_url(request)}"></iframe>`).appendTo(d.body);
    d.show();
  };
  frappe_sign.open_sign_dialog = function(token, frm) {
    const d = new frappe.ui.Dialog({ title: __("Sign"), size: "large" });
    d.show();
    frappe_sign.mount_sign_widget(d.body, token, {
      on_done: (status) => {
        d.hide();
        frappe.show_alert({ message: status === "Signed" ? __("Signed") : __("Rejected"), indicator: "green" });
        if (frm)
          frm.reload_doc();
      }
    });
  };
  frappe_sign.open_request_dialog = async function(frm, config, request_name) {
    await frappe_sign.load_libs();
    const standalone = frm.doctype === "Signature Request";
    const sending = !request_name || standalone && frm.doc.status === "Draft";
    const signers = [];
    const COLORS = ["#2490ef", "#e2495e", "#29cd42", "#f4a93a", "#9a5cf3", "#16b4c4"];
    const DEFAULT_BOX = { w: 160, h: 50 };
    let next_color = 0;
    let active = null;
    let in_order = 0;
    if (request_name) {
      const existing = await frappe.xcall("frappe_sign.frappe_sign.api.get_editable_request", {
        request: request_name
      });
      existing.signers.forEach((s) => signers.push(__spreadProps(__spreadValues({}, s), { color: COLORS[next_color++ % COLORS.length] })));
      in_order = existing.sign_in_order;
      active = signers[0] || null;
    }
    const d = new frappe.ui.Dialog({
      title: sending ? __("Request Signature") : __("Update Signature Request {0}", [request_name]),
      size: "extra-large",
      fields: [
        {
          fieldname: "signer_type",
          fieldtype: "Select",
          label: __("Signer Type"),
          options: config.allow_external_signers ? ["User", "Employee", "Customer", "Supplier", "Email"] : ["User"],
          default: "User",
          onchange: () => on_type_change()
        },
        {
          fieldname: "signer_reference",
          fieldtype: "Dynamic Link",
          label: __("Signer Reference"),
          options: "signer_type",
          onchange: () => prefill_from_reference()
        },
        { fieldname: "cb_signer", fieldtype: "Column Break" },
        { fieldname: "signer_name", fieldtype: "Data", label: __("Signer Name") },
        { fieldname: "signer_email", fieldtype: "Data", label: __("Signer Email"), options: "Email" },
        {
          fieldname: "add_signer",
          fieldtype: "Button",
          label: __("Add Signer"),
          click: () => add_signer()
        },
        { fieldname: "sb_list", fieldtype: "Section Break" },
        {
          fieldname: "sign_in_order",
          fieldtype: "Check",
          label: __("Signers sign in order (top to bottom)"),
          description: __("Each signer is emailed when the one before them has signed."),
          default: in_order,
          onchange: () => render_list()
        },
        { fieldname: "signer_list", fieldtype: "HTML" },
        { fieldname: "sb_place", fieldtype: "Section Break", label: __("Placement") },
        { fieldname: "placement", fieldtype: "HTML" }
      ],
      primary_action_label: sending ? __("Request Signature") : __("Update"),
      primary_action: () => submit()
    });
    d.show();
    function on_type_change() {
      const is_email = d.get_value("signer_type") === "Email";
      d.set_df_property("signer_reference", "hidden", is_email);
      d.set_df_property("signer_name", "read_only", !is_email);
      d.set_df_property("signer_email", "read_only", !is_email);
      d.set_values({ signer_reference: "", signer_name: "", signer_email: "" });
    }
    on_type_change();
    async function prefill_from_reference() {
      const type = d.get_value("signer_type");
      const ref = d.get_value("signer_reference");
      d.set_values({ signer_name: "", signer_email: "" });
      if (!ref || type === "Email")
        return;
      const details = await frappe.xcall("frappe_sign.frappe_sign.api.get_signer_details", {
        signer_type: type,
        reference: ref
      });
      if (d.get_value("signer_reference") === ref)
        d.set_values(details);
    }
    function add_signer() {
      const row = {
        signer_type: d.get_value("signer_type"),
        signer_reference: d.get_value("signer_reference") || null,
        signer_name: d.get_value("signer_name"),
        signer_email: d.get_value("signer_email"),
        color: COLORS[next_color++ % COLORS.length],
        sign_boxes: []
      };
      if (row.signer_type !== "Email" && !row.signer_reference) {
        frappe.msgprint(__("Pick the {0} who should sign.", [__(row.signer_type)]));
        return;
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
      signers.push(row);
      d.set_value("signer_reference", "");
      d.set_value("signer_name", "");
      d.set_value("signer_email", "");
      set_active(row);
    }
    function render_list() {
      const ordered = d.get_value("sign_in_order");
      const rows = signers.map(
        (s, i) => `<tr class="sign-signer-row ${s === active ? "is-active" : ""}" data-i="${i}" style="--c:${s.color}">
					<td>${ordered ? `<span class="sign-order">
								<a class="sign-move ${i ? "" : "invisible"}" data-by="-1" title="${__("Move up")}">\u2191</a>
								<a class="sign-move ${i < signers.length - 1 ? "" : "invisible"}" data-by="1" title="${__("Move down")}">\u2193</a>
								${i + 1}.</span> ` : ""}<span class="sign-signer-swatch" style="background:${s.color}"></span>${frappe.utils.escape_html(s.signer_name)}</td>
					<td>${frappe.utils.escape_html(s.signer_email)}</td>
					<td>${s.signer_type}</td>
					<td>${s.sign_boxes.length ? `${s.sign_boxes.length === 1 ? __("1 place") : __("{0} places", [s.sign_boxes.length])} \xB7 <a class="sign-goto">${__("Go to box")}</a>` : `<span class="text-danger">${__("Not placed")}</span>`}</td>
					<td><a class="text-danger sign-remove">${__("Remove")}</a></td>
				</tr>`
      ).join("");
      const $w = $(d.fields_dict.signer_list.wrapper).html(
        signers.length ? `<div class="sign-signers-scroll"><table class="table table-bordered table-sm"><thead><tr>
						<th>${__("Name")}</th><th>${__("Email")}</th><th>${__("Type")}</th>
						<th>${__("Box")}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : `<div class="text-muted">${__("No signers added yet.")}</div>`
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
    const $place = $(d.fields_dict.placement.wrapper);
    const pages = [];
    const pdf_url = standalone ? frappe_sign.request_pdf_url(frm.doc.name) : `/api/method/frappe_sign.frappe_sign.api.preview_source_pdf?reference_doctype=${encodeURIComponent(frm.doctype)}&reference_name=${encodeURIComponent(frm.doc.name)}`;
    function set_active(s) {
      active = s;
      render_list();
      draw_boxes();
      $place.find(".sign-place-hint").text(
        active ? __(
          "Click wherever {0} should sign; each click adds another place. Drag a box to move it, its corner to resize it, or \xD7 to remove it.",
          [active.signer_name]
        ) : __("Add a signer above, then click on the document where they should sign.")
      );
    }
    const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));
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
      if (!page)
        return;
      $place.find(".sign-place-wrap")[0].scrollTop = page.el.offsetTop + box.y * page.scale - 40;
    }
    function draw_boxes() {
      $place.find(".sign-place-box").remove();
      signers.forEach((s) => {
        s.sign_boxes.forEach((box, i) => {
          const page = pages[box.page];
          if (!page)
            return;
          const $b = $(`<div class="sign-place-box">
						<span class="sign-place-label"></span>
						<span class="sign-place-remove" title="${__("Remove")}">&times;</span>
						<span class="sign-place-resize"></span>
					</div>`).css({ left: box.x * page.scale, top: box.y * page.scale, width: box.w * page.scale, height: box.h * page.scale }).toggleClass("is-active", s === active).appendTo(page.el);
          $b[0].style.setProperty("--c", s.color);
          $b.find(".sign-place-label").text(s.sign_boxes.length > 1 ? `${s.signer_name} \xB7 ${i + 1}` : s.signer_name);
          $b.find(".sign-place-remove").on("click", () => remove_box(s, box));
          $b[0].addEventListener("pointerdown", (e) => drag_box(e, s, box, $b[0]));
        });
      });
    }
    function drag_box(e, s, box, el) {
      if (e.target.classList.contains("sign-place-remove"))
        return;
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
        e.preventDefault();
        canvas.setPointerCapture(e.pointerId);
        const s = active;
        const a = at(e);
        let box = null;
        const move = (ev) => {
          const b = at(ev);
          if (!box && Math.abs(b.x - a.x) < 10 && Math.abs(b.y - a.y) < 10)
            return;
          const pts = to_points(page_idx, { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) });
          if (box)
            Object.assign(box, pts);
          else
            s.sign_boxes.push(box = pts);
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
                h
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
      for (let i = 0; !$place.width() && i < 60; i++)
        await new Promise(requestAnimationFrame);
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
      if (!signers.length)
        return frappe.msgprint(__("Add at least one signer."));
      const unplaced = signers.find((s) => !s.sign_boxes.length);
      if (unplaced) {
        return frappe.msgprint(__("Place a signature box for {0} before sending.", [unplaced.signer_name]));
      }
      frappe.call(
        request_name ? {
          method: "frappe_sign.frappe_sign.api.update_signature_request",
          args: { request: request_name, signers, sign_in_order: d.get_value("sign_in_order") },
          freeze: true,
          freeze_message: sending ? __("Sending for signature...") : __("Updating signature request...")
        } : {
          method: "frappe_sign.frappe_sign.api.create_signature_request",
          args: {
            reference_doctype: frm.doctype,
            reference_name: frm.doc.name,
            signers,
            sign_in_order: d.get_value("sign_in_order")
          },
          freeze: true,
          freeze_message: __("Sending for signature...")
        }
      ).then(() => {
        d.hide();
        frappe.show_alert({
          message: sending ? __("Signature requested") : __("Signature request updated"),
          indicator: "green"
        });
        frm.reload_doc();
      });
    }
  };
})();
//# sourceMappingURL=frappe_sign.bundle.RXDK2STO.js.map
