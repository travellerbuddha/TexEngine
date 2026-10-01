"""Y-9 (audit Part 2F-2, ADR-048): an inventory pool's key is its first room type by name, disabled ones included.

Until now ``avail.pool_of`` read only the OPEN members of a pool and keyed it by the first of them: disabling the
first member moved the key to the next one, and the rows kept under the old key (``TEX Inventory Day``: closed
nights, manual adjustments, oversell limits, a configured base) were no longer read. The key is now the first member
of all, a disabled one included, so a pool whose first member is disabled reads its rows under that member.

Per hotel and pool: the old key = its first open member (what ``pool_of`` returned until now), the new key = the
first member of all. Where they differ:

* the old key has rows: they are the ones in force today. The rows under the new key (the disabled first member's,
  kept from before it was disabled: nobody reads them today) are dropped, every date, and the old key's rows move to
  the new key (``room_type`` and the date-derived ``name``, as the controller names a row);
* the old key has no rows: nothing was set under it. The rows of the disabled first member, if any, come back into
  force as they are (the hotel's last settings before it disabled that room type); they are only counted.

A pool whose members are all disabled is left alone. Raw SQL on the room types and the days, by name, without
touching ``modified``; NULL ``tex_inventory_pool`` or an empty one is no pool, and a NULL ``disabled`` is open (the
field defaults to 0). Prints counts only; a second run finds the old key without rows and moves nothing.
"""

import frappe

from kamra.tex_commercial.doctype.tex_inventory_day.tex_inventory_day import inventory_day_name

TYPES = """SELECT name, property, tex_inventory_pool, IFNULL(disabled, 0) FROM `tabRoom Type`
	WHERE tex_inventory_pool IS NOT NULL AND tex_inventory_pool != ''"""


def execute():
	pools: dict[tuple[str, str], list[tuple[str, int]]] = {}
	for name, prop, pool, disabled in frappe.db.sql(TYPES):
		pools.setdefault((prop, pool), []).append((name, int(disabled)))
	rekeyed = moved = kept = 0
	for key in sorted(pools):
		members = sorted(pools[key])
		new = members[0][0]
		opened = [name for name, disabled in members if not disabled]
		if not opened or opened[0] == new:
			continue                      # every member disabled, or the first one is open: the key was right
		old = opened[0]
		old_rows = frappe.db.sql("SELECT name, inventory_date FROM `tabTEX Inventory Day` WHERE room_type = %s", old)
		if not old_rows:
			if frappe.db.exists("TEX Inventory Day", {"room_type": new}):
				kept += 1                 # the disabled first member's rows are in force again, untouched
			continue
		frappe.db.sql("DELETE FROM `tabTEX Inventory Day` WHERE room_type = %s", new)
		for name, day in old_rows:
			frappe.db.sql("UPDATE `tabTEX Inventory Day` SET name = %s, room_type = %s WHERE name = %s",
			              (inventory_day_name(new, day), new, name))
		rekeyed += 1
		moved += len(old_rows)
	print(f"p58: {rekeyed} pool(s) re-keyed ({moved} row(s) moved), {kept} pool(s) keep the rows of their "
	      f"disabled first member")
