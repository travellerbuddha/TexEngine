"""Call-centre channel binding (G-41, ADR-050).

Staff now price and book only on the sales channels of their permission profiles (the call
centre when a profile names none), or on every channel with ``price.any_channel``. Before,
anyone who could price could do so on any channel. So that nobody who legitimately priced on
other channels loses it, and nobody gains anything:

- the seeded profiles whose defaults carry ``price.any_channel`` get it (Hotel Admin, Group
  Admin, Enterprise Admin, Revenue Manager);
- a custom profile that may publish contracts (``contract.publish``) gets it: it already sets
  the prices of every channel it publishes for;
- every other profile keeps its capabilities and sells on the call centre (the default for a
  profile without a channel list). Administrators add channels to a profile where a desk sells
  on another one (e.g. a B2B desk).

Re-runnable; prints what it changed.
"""

import frappe

from kamra.tex.security.capabilities import ANY_CHANNEL, DEFAULT_PROFILES


def execute():
	frappe.reload_doc("tex_platform", "doctype", "tex_profile_channel")
	frappe.reload_doc("tex_platform", "doctype", "tex_permission_profile")
	added = []
	for name in frappe.get_all("TEX Permission Profile", pluck="name", order_by="name asc"):
		caps = set(frappe.get_all("TEX Profile Capability",
		                          filters={"parent": name, "parenttype": "TEX Permission Profile"},
		                          pluck="capability"))
		if ANY_CHANNEL in caps:
			continue
		system_default = ANY_CHANNEL in DEFAULT_PROFILES.get(name, frozenset())
		if not (system_default or "contract.publish" in caps):
			continue
		doc = frappe.get_doc("TEX Permission Profile", name)
		doc.append("capabilities", {"capability": ANY_CHANNEL})
		doc.save(ignore_permissions=True)
		added.append(name)
	from kamra.tex.security import scope

	scope.clear_cache()
	print(f"p29: {ANY_CHANNEL} added to {len(added)} profile(s): {', '.join(added) or '—'}; every other profile "
	      "sells on the call centre unless a channel list is set on it")
