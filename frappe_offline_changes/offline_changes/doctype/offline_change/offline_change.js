frappe.ui.form.on("Offline Change", {
	refresh(frm) {
		const waiting = ["Held", "Refused", "Failed"].includes(frm.doc.status);
		frm.disable_save();
		if (waiting && frm.perm[0].write) {
			frm.add_custom_button(__("Resolve"), () => resolve(frm)).addClass("btn-primary");
			frm.add_custom_button(__("Reject"), () => reject(frm));
			if (frm.doc.field_changes.some((row) => row.conflict)) {
				frm.set_intro(
					__(
						"For each field in conflict, choose the value the record keeps: the device's, the server's, or another. Then resolve."
					),
					"orange"
				);
			}
		} else if (frm.doc.has_lost_values && !frm.doc.closed && frm.perm[0].write) {
			frm.set_intro(
				__(
					"This change was applied over another value, kept below. Close it once you have seen it."
				),
				"blue"
			);
			frm.add_custom_button(__("Close"), () =>
				frm.call("close").then(() => frm.reload_doc())
			);
		}
	},
});

function resolve(frm) {
	frappe.confirm(__("Apply this change to the record with the values chosen?"), () => {
		frm.call("resolve").then(() => frm.reload_doc());
	});
}

function reject(frm) {
	frappe.prompt(
		{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		({ reason }) => frm.call("reject", { reason }).then(() => frm.reload_doc()),
		__("Reject the change"),
		__("Reject")
	);
}
