frappe.ui.form.on("Digital Invoice Setting", {
	refresh(frm) {
		if (!frm.is_new()) {
			di_settings_add_sync_buttons(frm);
		}

		frm.toggle_display("scenarios", cint(frm.doc.sandbox));
	},

	sandbox(frm) {
		frm.toggle_display("scenarios", cint(frm.doc.sandbox));
	},
});

function di_settings_add_sync_buttons(frm) {
	let sync_types = [
		{ label: __("Sync Provinces"), data_type: "provinces" },
		{ label: __("Sync HS Codes"), data_type: "hs_codes" },
		{ label: __("Sync HS Code UOMs"), data_type: "hs_code_uoms" },
		{ label: __("Sync UOMs"), data_type: "uoms" },
		{ label: __("Sync Sale Types"), data_type: "sale_types" },
		{ label: __("Sync SRO Item Codes"), data_type: "sro_item_codes" },
	];

	sync_types.forEach(({ label, data_type }) => {
		frm.add_custom_button(label, () => {
			frappe.xcall("di.api.sync_reference_data", {
				data_type: data_type,
				company: frm.doc.company,
			}).then(() => {
				frappe.show_alert({
					message: __("Syncing {0} in background", [data_type]),
					indicator: "blue",
				});
			}).catch((err) => {
				frappe.show_alert({
					message: __("Sync failed: {0}", [err.message || err]),
					indicator: "red",
				});
			});
		}, __("Sync Reference Data"));
	});
}
