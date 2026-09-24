"""Channel distribution (G-69).

- New: TEX Channel Mapping / ARI Day / Inbound; the outbox gets a kind and a claim.
- A connection's API key is a bearer secret: it moves from a plain column to the encrypted
  store (the column keeps asterisks, like every Password field).
- Existing outbox rows are reservation events; channel-manager connections no longer
  receive reservation events (they get ARI).
- channel.view / channel.manage for the default profiles that hold them, once, at the upgrade: a
  forced re-run does not give back a capability removed since (G-76).
"""

import frappe
from frappe.utils.password import set_encrypted_password

from kamra.tex.security.capabilities import DEFAULT_PROFILES
from kamra.tex.setup import ran_before

CAPS = ("channel.view", "channel.manage")


def execute():
	for dt in ("tex_integration_connection", "tex_integration_outbox", "tex_channel_mapping", "tex_channel_ari_day",
	           "tex_channel_inbound"):
		frappe.reload_doc("tex_connect", "doctype", dt)
	for dt in ("tex_booking", "tex_reservation_revision"):
		frappe.reload_doc("tex_booking", "doctype", dt)
	frappe.reload_doc("kamra", "doctype", "reservation")
	for r in frappe.db.sql("SELECT name, api_key FROM `tabTEX Integration Connection` WHERE IFNULL(api_key, '') != ''",
	                       as_dict=True):
		if set(r.api_key) == {"*"}:
			continue                              # already encrypted
		set_encrypted_password("TEX Integration Connection", r.name, r.api_key, "api_key")
		frappe.db.sql("UPDATE `tabTEX Integration Connection` SET api_key=%s WHERE name=%s",
		              ("*" * len(r.api_key), r.name))
	frappe.db.sql("UPDATE `tabTEX Integration Outbox` SET kind='Reservation' WHERE IFNULL(kind, '') = ''")
	frappe.db.sql("""UPDATE `tabTEX Integration Outbox` o JOIN `tabTEX Integration Connection` c ON c.name = o.connection
	                 SET o.status='Dead', o.last_error='channel managers receive ARI, not reservation events (G-69)'
	                 WHERE c.category='Channel Manager' AND o.kind='Reservation' AND o.status IN ('Pending', 'Failed')""")
	for name, caps in DEFAULT_PROFILES.items() if not ran_before(__name__) else ():
		if not frappe.db.exists("TEX Permission Profile", name):
			continue
		doc = frappe.get_doc("TEX Permission Profile", name)
		have = {c.capability for c in doc.capabilities}
		missing = [c for c in CAPS if c in caps and c not in have]
		for c in missing:
			doc.append("capabilities", {"capability": c})
		if missing:
			doc.save(ignore_permissions=True)
	from kamra.tex.setup import ensure_indexes

	ensure_indexes()
