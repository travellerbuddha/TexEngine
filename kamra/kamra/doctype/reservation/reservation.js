// Copyright (c) 2026, HeyKoala and contributors
// For license information, please see license.txt

// TEX Engine (ADR-052 review): the Desk form says when the hotel is sold through TEX, where the
// server refuses to create a stay or change its dates, room, party or price outside TEX.
frappe.ui.form.on("Reservation", {
	refresh(frm) {
		show_tex_mode(frm);
	},
	property(frm) {
		show_tex_mode(frm);
	},
});

function show_tex_mode(frm) {
	frm.set_intro("");
	if (!frm.doc.property) return;
	frappe
		.xcall("kamra.tex.api.session.hotel_mode", { property: frm.doc.property })
		.then((r) => {
			if (!r || r.property !== frm.doc.property || !r.tex_mode) return;
			if (r.tex_mode === "live") {
				frm.set_intro(
					__(
						"{0} is sold through TEX: create reservations and change their dates, room, party or price in TEX (Reservations → CRS or Call Center). Notes and other details can still be edited here.",
						[frappe.utils.escape_html(frm.doc.property)]
					),
					"blue"
				);
			} else {
				frm.set_intro(
					__(
						"{0} is joining TEX: the Desk still sells it at its current prices until an administrator sets it live in TEX.",
						[frappe.utils.escape_html(frm.doc.property)]
					),
					"orange"
				);
			}
		})
		.catch(() => {});
}
