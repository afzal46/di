frappe.provide("digclient.digital_invoice_preview");

digclient.digital_invoice_preview.make_dialog = function (invoice) {

    const columns = [
        { name: "HS Code", id: "hsCode", width: 100, editable: false },
        { name: "Description", id: "productDescription", width: 200, editable: false },
        { name: "Qty", id: "quantity", width: 80, editable: false },
        { name: "Rate", id: "fixedNotifiedValueOrRetailPrice", width: 100, editable: false },
        { name: "Discount", id: "discount", width: 100, editable: false },
        { name: "Amount", id: "valueSalesExcludingST", width: 120, editable: false },
        { name: "Sales Tax Rate", id: "rate", width: 120, editable: false },
        { name: "Sales Tax Amount", id: "salesTaxApplicable", width: 120, editable: false },
        { name: "Further Tax", id: "furtherTax", width: 120, editable: false },
        { name: "Extra Tax", id: "extraTax", width: 120, editable: false },
        { name: "Total", id: "totalValues", width: 120, editable: false },
    ];

    let dialog = new frappe.ui.Dialog({
        size: "extra-large",
        title: __("Digital Invoice Preview"),
        fields: [{ fieldtype: "HTML", fieldname: "preview_html" }],
    });
    setTimeout(function () {
        new frappe.DataTable(dialog.get_field("preview_html").wrapper, {
            columns: columns,
            data: invoice.items,
            dynamicRowHeight: false,
            checkboxColumn: false,
            inlineFilters: false,
        });
        const datatable = new frappe.DataTable(dialog.get_field("preview_html").wrapper, {
            dynamicRowHeight: false,
            checkboxColumn: false,
            inlineFilters: false,
        });
        datatable.refresh(invoice.items, columns);
    }, 200);

    dialog.show();
};

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		di_toggle_section(frm);
		di_add_buttons(frm);
		di_show_qr(frm);
		di_show_scenario(frm);
	},

	company(frm) {
		di_toggle_section(frm);
	},

	is_pos(frm) {
		di_toggle_section(frm);
	},

	customer(frm) {
		di_toggle_section(frm);
	}
});

frappe.ui.form.on("Sales Invoice Item", {
	sales_type(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.sales_type && row.item_code) {
			frappe.model.set_value(cdt, cdn, "sales_type", row.sales_type);
		}
	}
});

function _is_pos_invoice(frm) {
	return cint(frm.doc.is_pos) === 1;
}

function _hide_all_di(frm) {
	frm.toggle_display("di_section", false);
	frm.toggle_display("di_scenario_id", false);
	_toggle_di_item_fields(frm, false);
}

function di_toggle_section(frm) {
	if (!frm.doc.company || _is_pos_invoice(frm)) {
		_hide_all_di(frm);
		return;
	}

	frappe
		.xcall("di.digital_invoicing.doctype.digital_invoice_setting.digital_invoice_setting.is_enabled", {
			company: frm.doc.company
		})
		.then((enabled) => {
			if (!enabled) {
				_hide_all_di(frm);
				return;
			}

			if (frm.doc.customer) {
				frappe.db
					.get_value("Customer", frm.doc.customer, "enable_digital_invoicing")
					.then((r) => {
						let customer_di =
							r && r.message && cint(r.message.enable_digital_invoicing);
						_apply_di_visibility(frm, !!customer_di);
					});
			} else {
				_hide_all_di(frm);
			}
		});
}

function _apply_di_visibility(frm, show) {
	frm.toggle_display("di_section", show);
	frm.toggle_display("di_scenario_id", false);
	_toggle_di_item_fields(frm, show);

	if (show) {
		frappe.db.get_value("Digital Invoice Setting", { company: frm.doc.company }, "sandbox").then((r) => {
			if (r && r.message && cint(r.message.sandbox)) {
				frm.toggle_display("di_scenario_id", true);
			}
		});
	}
}

function _toggle_di_item_fields(frm, show) {
	let fields = [
		"hs_code",
		"hs_uom",
		"sales_type",
		"sro_serial_no",
		"schedule_no",
		"fed_payable",
		"di_taxes_section",
		"column_break_di_item"
	];
	fields.forEach((f) => {
		frm.fields_dict.items && frm.fields_dict.items.grid.toggle_display(f, show);
	});
}

function di_add_buttons(frm) {
	// this line added by afzal (to restrict the button for only DI Posting User role)
	if (!frappe.user.has_role("DI Posting User")) return;
	

	if (frm.doc.docstatus !== 1) return;
	if (_is_pos_invoice(frm)) return;
	if (!frm.doc.customer) return;

	frappe.db.get_value("Customer", frm.doc.customer, "enable_digital_invoicing").then((r) => {
		if (!r || !r.message || !cint(r.message.enable_digital_invoicing)) return;

		if (!frm.doc.is_posted && !frm.doc.integration_id) {
			frm.add_custom_button(
				__("DI Preview"),
				() => {
					frappe
						.xcall("di.api.get_invoice_preview", {
							doctype: frm.doc.doctype,
							name: frm.doc.name
						})
						.then((payload) => {
							digclient.digital_invoice_preview.make_dialog(payload)
						});
				},
				__("Digital Invoicing")
			);

			if (!frm.doc.is_posted) {
				frm.add_custom_button(
					__("Post to FBR"),
					() => {
						frappe.confirm(
							__("Are you sure you want to post this invoice to FBR?"),
							() => {
								frappe
									.xcall("di.api.resync_invoice", {
										doctype: frm.doc.doctype,
										name: frm.doc.name
									})
									.then(() => {
										frappe.msgprint(__("Invoice posted to FBR successfully"));
										frm.reload_doc();
									});
							}
						);
					},
			
				);
			}

			frm.add_custom_button(
				__("Validate with FBR"),
				() => {
					frappe
						.xcall("di.api.validate_invoice", {
							doctype: frm.doc.doctype,
							name: frm.doc.name
						})
						.then((response) => {
							let vr = response.validationResponse || {};
							let status = vr.status || "Unknown";
							let msg =
								status === "Valid"
									? __("Invoice is valid according to FBR")
									: __("Validation result: {0}", [vr.error || status]);

							frappe.msgprint({
								title: __("FBR Validation Result"),
								indicator: status === "Valid" ? "green" : "red",
								message: msg
							});
						});
				},
				__("Digital Invoicing")
			);

			// frm.add_custom_button(
			// 	__("Verify Buyer"),
			// 	() => {
			// 		frappe
			// 			.xcall("di.api.verify_buyer", {
			// 				customer: frm.doc.customer
			// 			})
			// 			.then((result) => {
			// 				frappe.msgprint({
			// 					title: __("Buyer Verification"),
			// 					message: `<pre>${JSON.stringify(result, null, 2)}</pre>`
			// 				});
			// 			});
			// 	},
			// 	__("Digital Invoicing")
			// );
		}
	});
}

function di_show_qr(frm) {
	if (_is_pos_invoice(frm)) return;

	if (frm.doc.integration_id && frm.doc.is_posted) {
		frappe
			.xcall("di.api.get_qr_code", {
				integration_id: frm.doc.integration_id
			})
			.then((qr_data) => {
				if (!qr_data) return;
				let html = `
					<div style="text-align:center;padding:10px;">
						<img src="${qr_data}" style="width:96px;height:96px;" />
						<p style="margin-top:5px;font-size:11px;color:#888;">
							FBR: ${frm.doc.integration_id || ""}
						</p>
					</div>
				`;
				frm.sidebar && frm.sidebar.add_user_action && frm.sidebar.add_user_action(html);
			});
		if (frm.dashboard) {
			frm.set_intro("");
			frm.set_eintro(
				`<span class="indicator-pill green">
					<span>FBR Posted: ${frm.doc.integration_id}</span>
				</span>`,
				"green"
			);
		}
	}
}

function di_show_scenario(frm) {
	if (_is_pos_invoice(frm)) return;

	if (frm.doc.docstatus === 0 && frm.doc.company) {
		frappe.db.get_value("Digital Invoice Setting", { company: frm.doc.company }, "sandbox").then((r) => {
			if (r && r.message && cint(r.message.sandbox)) {
				frm.toggle_display("di_scenario_id", true);
			}
		});
	}
}
