"""G-76 (ADR-058): the lookups by TEX booking, e-mail queue row and reservation keep their index.

p03, p13 and p23 created single-column indexes on ``Reservation.tex_booking`` (``tex_booking_idx``),
``TEX Extra Allocation.reservation`` (``tex_xalloc_res``) and ``TEX Communication.email_queue``
(``tex_comm_email_queue``). Frappe drops a single-column index on a field without ``search_index``
whenever it syncs that DocType again, and ``add_index`` keeps no property setter during a
migration: on the dev bench the first and the last were gone, and the second goes with the next
sync of its DocType. Their replacements are composite (``tex_booking`` + ``tex_room_index``,
``reservation`` + ``status``, ``email_queue`` + ``status``), which Frappe's sync leaves alone, and
are created here where missing. An old single-column index still present is left to Frappe's next
sync. Idempotent: an index that exists is not created again.
"""


def execute():
	from kamra.tex import setup

	missing = [name for _dt, _fields, name in setup.missing_indexes()]
	setup.ensure_indexes()
	print(f"p39: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}")
