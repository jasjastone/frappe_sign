// Copyright (c) 2026, jasjastone and contributors
// For license information, please see license.txt

frappe.ui.form.on("Signable Document Type", {
	setup(frm) {
		// Only the print formats of the chosen doctype.
		frm.set_query("default_print_format", () => ({
			filters: { doc_type: frm.doc.document_type, disabled: 0 },
		}));
	},

	document_type(frm) {
		frm.set_value("default_print_format", "");
	},
});
