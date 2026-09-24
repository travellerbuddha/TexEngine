// TEX Engine is a network service derived from Kamra PMS under AGPL-3.0: Desk users are offered
// the running version's source too (section 13, ADR-060 review), in Help > About. The address is
// kamra.tex.entry.source_url(), sent with the boot (extend_bootinfo).
(function () {
	const UPSTREAM = "https://github.com/Kamra-PMS/kamra-pms";
	const LICENSE = "https://www.gnu.org/licenses/agpl-3.0.html";
	const FALLBACK = "https://github.com/travellerbuddha/TexEngine";

	function link(href, text) {
		return $("<a target='_blank' rel='noopener noreferrer'></a>").attr("href", href).text(text);
	}

	function offer() {
		const url = /^https:\/\/\S+$/.test((frappe.boot && frappe.boot.tex_source_url) || "")
			? frappe.boot.tex_source_url
			: FALLBACK;
		const sub = $("<div class='about-info-sub'></div>")
			.append(document.createTextNode(__("Based on") + " "))
			.append(link(UPSTREAM, "Kamra PMS"))
			.append(document.createTextNode(" · "))
			.append(link(LICENSE, "AGPL-3.0"))
			.append(document.createTextNode(" · "))
			.append(link(url, __("Source Code")));
		return $("<div class='about-info-row' data-tex-source-notice='1'></div>").append(
			$("<div class='about-info-content'></div>")
				.append($("<div class='about-info-title'></div>").text("TEX Engine"))
				.append(sub)
		);
	}

	function wrap() {
		const misc = frappe.ui && frappe.ui.misc;
		if (!misc || !misc.about || misc.about.__tex) return false;
		const about = misc.about;
		misc.about = function () {
			const out = about.apply(this, arguments);
			const d = misc.about_dialog;
			if (d && !$(d.body).find("[data-tex-source-notice]").length) {
				$(d.body).find(".about-info-rows").first().append(offer());
			}
			return out;
		};
		misc.about.__tex = true;
		return true;
	}

	if (!wrap()) $(document).on("startup", wrap);
})();
