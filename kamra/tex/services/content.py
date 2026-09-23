"""Guest-facing content in the guest's language (R-49).

Hotels write room, rate plan, extra and policy texts once (usually in English or
Turkish); ``TEX Content Translation`` rows add the other languages. Guest API
responses are localised here, after pricing: only display text changes — codes,
amounts and the frozen contract payload never do. A missing translation falls back
to the hotel's own text.
"""

from __future__ import annotations

import copy

import frappe
from frappe.utils import now_datetime

LANGS = ("tr", "en", "de", "ru", "ro", "pl")

# translatable fields per record type (the hotel's own field names)
FIELDS: dict[str, tuple[str, ...]] = {
	"Room Type": ("room_type_name", "description"),
	"Rate Plan": ("rate_plan_name", "tex_inclusions"),
	"TEX Extra": ("extra_name", "description"),
	"Property": ("showcase_description",),
	"TEX Cancellation Policy": ("policy_name", "description"),
	"TEX Payment Policy": ("policy_name", "description"),
}

_CACHE_KEY = "tex_content_translation"


def record_property(doctype: str, name: str) -> str | None:
	if doctype == "Property":
		return name if frappe.db.exists("Property", name) else None
	if doctype not in FIELDS:
		return None
	return frappe.db.get_value(doctype, name, "property")


def guest_language(explicit: str | None = None) -> str | None:
	"""The guest's language: an explicit value, else the request language (Frappe reads
	the booking app's Accept-Language)."""
	lang = (explicit or getattr(frappe.local, "lang", None) or "").strip().lower()[:2]
	return lang if lang in LANGS else None


def clear_cache(property: str | None = None) -> None:
	if property is None:
		frappe.cache.delete_value(_CACHE_KEY)
	else:
		frappe.cache.hdel(_CACHE_KEY, property)


def nights_label(n: int, lang: str | None) -> str:
	"""'3 nights' in the guest's language (CLDR plural forms)."""
	lang = lang or "en"
	if lang == "tr":
		word = "gece"
	elif lang == "de":
		word = "Nacht" if n == 1 else "Nächte"
	elif lang == "ro":
		word = "noapte" if n == 1 else "nopți"
	elif lang in ("ru", "pl"):
		one, few, many = ("ночь", "ночи", "ночей") if lang == "ru" else ("noc", "noce", "nocy")
		if lang == "ru" and n % 10 == 1 and n % 100 != 11:
			word = one
		elif lang == "pl" and n == 1:
			word = one
		elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
			word = few
		else:
			word = many
	else:
		word = "night" if n == 1 else "nights"
	return f"{n} {word}"


def _table(property: str) -> dict[tuple[str, str, str, str], str]:
	cached = frappe.cache.hget(_CACHE_KEY, property)
	if cached is None:
		cached = {f"{r.ref_doctype}\x1f{r.ref_name}\x1f{r.field}\x1f{r.language}": r.text
		          for r in frappe.get_all("TEX Content Translation", filters={"property": property},
		                                  fields=["ref_doctype", "ref_name", "field", "language", "text"])}
		frappe.cache.hset(_CACHE_KEY, property, cached)
	return cached


class Localizer:
	"""Looks texts up for one language across the hotels of a response."""

	def __init__(self, lang: str | None):
		self.lang = lang
		self._tables: dict[str, dict] = {}

	def text(self, property: str | None, doctype: str, name: str | None, field: str, default):
		if not (self.lang and property and name):
			return default
		if property not in self._tables:
			self._tables[property] = _table(property)
		return self._tables[property].get(f"{doctype}\x1f{name}\x1f{field}\x1f{self.lang}") or default

	# ── pieces of API responses ──

	def rate_plan(self, property: str, info: dict | None) -> dict | None:
		"""A localised COPY: rate-plan and policy dicts are shared with the cached
		contract terms and must never be changed in place."""
		if not info or not self.lang:
			return info
		info = copy.deepcopy(info)
		code = info.get("code")
		info["name"] = self.text(property, "Rate Plan", code, "rate_plan_name", info.get("name"))
		inclusions = self.text(property, "Rate Plan", code, "tex_inclusions", None)
		if inclusions:
			info["inclusions"] = [x.strip() for x in inclusions.splitlines() if x.strip()]
		for key, doctype in (("cancellation_policy", "TEX Cancellation Policy"),
		                     ("payment_policy", "TEX Payment Policy")):
			pol = info.get(key)
			if isinstance(pol, dict) and pol.get("id"):
				pol["name"] = self.text(property, doctype, pol["id"], "policy_name", pol.get("name"))
				pol["description"] = self.text(property, doctype, pol["id"], "description", pol.get("description"))
		return info

	def quote(self, property: str, q: dict | None) -> dict | None:
		if not q or not self.lang:
			return q
		if q.get("rate_plan"):
			q["rate_plan"] = self.rate_plan(property, q["rate_plan"])
		names: dict[str, str] = {}
		for e in q.get("extras") or []:
			if e.get("code"):
				# the extra that was sold (its revision's record), not whichever record has the code
				ref = _extra_root(e["revision"]) if e.get("revision") else _extra_name(property, e["code"])
				e["name"] = names[e["code"]] = self.text(property, "TEX Extra", ref, "extra_name", e.get("name"))
		req = q.get("request") or {}
		for line in q.get("lines") or []:
			if line.get("kind") == "ACCOMMODATION" and line.get("code") == req.get("room_type"):
				room = self.room_type_name(property, req.get("room_type"), None)
				if room:
					n = int(float(line.get("quantity") or 0))
					line["description"] = f"{room} · {req.get('board')} · {nights_label(n, self.lang)}"
			elif line.get("kind") == "EXTRA" and line.get("code") in names:
				line["description"] = names[line["code"]]
		return q

	def search(self, res: dict) -> dict:
		if not self.lang:
			return res
		for p in res.get("properties") or []:
			prop = p.get("property")
			for rt, c in (p.get("rooms") or {}).items():
				c["name"] = self.text(prop, "Room Type", rt, "room_type_name", c.get("name"))
				c["description"] = self.text(prop, "Room Type", rt, "description", c.get("description"))
			for group in ("offers", "unavailable"):
				for o in p.get(group) or []:
					if o.get("rate_plan_info"):
						o["rate_plan_info"] = self.rate_plan(prop, o["rate_plan_info"])
					for r in o.get("rooms") or []:
						self.quote(prop, r.get("quote"))
		return res

	def extras(self, property: str, rows: list[dict]) -> list[dict]:
		for e in rows:
			name = _extra_root(e.get("name")) if e.get("name") else _extra_name(property, e.get("extra_code"))
			e["extra_name"] = self.text(property, "TEX Extra", name, "extra_name", e.get("extra_name"))
			e["description"] = self.text(property, "TEX Extra", name, "description", e.get("description"))
		return rows

	def hotel(self, property: str, row: dict) -> dict:
		row["showcase_description"] = self.text(property, "Property", property, "showcase_description",
		                                        row.get("showcase_description"))
		return row

	def room_type_name(self, property: str, room_type: str, default):
		return self.text(property, "Room Type", room_type, "room_type_name", default)


def _extra_name(property: str, code: str | None) -> str | None:
	"""The extra's root record: translations belong to the extra, not to one revision (G-20).
	A code can be reused after its extra was archived: the one on sale now wins, else the newest."""
	if not code:
		return None
	from kamra.tex.commercial.context import listed_extras

	live = [r for r in listed_extras(property, fields=("revision_of",)) if r.extra_code == code]
	if live:
		return live[0].revision_of or live[0].name
	row = frappe.db.get_value("TEX Extra", {"property": property, "extra_code": code}, ["name", "revision_of"],
	                          as_dict=True, order_by="creation desc")
	return (row.revision_of or row.name) if row else None


def _extra_root(name: str) -> str:
	return frappe.db.get_value("TEX Extra", name, "revision_of") or name


# ── administration ──────────────────────────────────────────────────────────


def _translatable_extras(property: str) -> list[dict]:
	"""One row per extra that is not archived (drafts and scheduled ones too, so they can be
	translated before they go on sale), with the text of its revision on sale now, else of
	its newest revision."""
	now = now_datetime()
	rows = frappe.get_all("TEX Extra", filters={"property": property,
	                                            "tex_status": ("in", ["Draft", "Active", "Superseded"])},
	                      fields=["name", "revision_of", "extra_name", "description", "tex_status", "active_from",
	                              "active_to", "creation"], order_by="creation desc")
	chains: dict[str, dict] = {}
	for r in rows:
		root = r.revision_of or r.name
		live = r.tex_status != "Draft" and r.active_from and r.active_from <= now and (
			not r.active_to or r.active_to > now)
		if root not in chains or (live and not chains[root]["live"]):
			chains[root] = {"row": r, "live": live}
	return sorted((c["row"] for c in chains.values()), key=lambda r: r.extra_name or "")


def items(property: str) -> list[dict]:
	"""Every translatable record of a hotel with its own text and its translations."""
	out = []

	def add(doctype: str, name: str, label: str, values: dict):
		out.append({"ref_doctype": doctype, "ref_name": name, "label": label,
		            "fields": {f: values.get(f) or "" for f in FIELDS[doctype]}, "translations": {}})

	d = frappe.db.get_value("Property", property, ["property_name", "showcase_description"], as_dict=True)
	if d:
		add("Property", property, d.property_name, d)
	for r in frappe.get_all("Room Type", filters={"property": property},
	                        fields=["name", "room_type_name", "description"], order_by="room_type_name asc"):
		add("Room Type", r.name, r.room_type_name, r)
	for r in frappe.get_all("Rate Plan", filters={"property": property},
	                        fields=["name", "rate_plan_name", "tex_inclusions"], order_by="rate_plan_name asc"):
		add("Rate Plan", r.name, r.rate_plan_name, r)
	for r in _translatable_extras(property):
		add("TEX Extra", r.revision_of or r.name, r.extra_name, r)
	for dt in ("TEX Cancellation Policy", "TEX Payment Policy"):
		for r in frappe.get_all(dt, filters={"property": property}, fields=["name", "policy_name", "description"],
		                        order_by="policy_name asc"):
			add(dt, r.name, r.policy_name, r)
	index = {(i["ref_doctype"], i["ref_name"]): i for i in out}
	for t in frappe.get_all("TEX Content Translation", filters={"property": property},
	                        fields=["ref_doctype", "ref_name", "field", "language", "text"]):
		item = index.get((t.ref_doctype, t.ref_name))
		if item:
			item["translations"].setdefault(t.language, {})[t.field] = t.text
	return out


def save(property: str, rows: list[dict]) -> dict:
	"""Upsert translations; an empty text removes one. Returns counts."""
	created = updated = deleted = 0
	for r in rows:
		doctype, name = r.get("ref_doctype"), r.get("ref_name")
		field, lang = r.get("field"), (r.get("language") or "").lower()
		text = (r.get("text") or "").strip()
		if doctype not in FIELDS or field not in FIELDS[doctype] or lang not in LANGS:
			frappe.throw(frappe._("Invalid translation row."))
		if record_property(doctype, name) != property:
			frappe.throw(frappe._("{0} {1} does not belong to this hotel.").format(doctype, name),
			             frappe.PermissionError)
		existing = frappe.db.get_value("TEX Content Translation", {"ref_doctype": doctype, "ref_name": name,
		                                                           "field": field, "language": lang})
		if not text:
			if existing:
				frappe.delete_doc("TEX Content Translation", existing, ignore_permissions=True)
				deleted += 1
			continue
		if len(text) > 4000:
			frappe.throw(frappe._("Text is too long (4000 characters at most)."))
		if existing:
			doc = frappe.get_doc("TEX Content Translation", existing)
			if doc.text != text:
				doc.text = text
				doc.save(ignore_permissions=True)
				updated += 1
		else:
			frappe.get_doc({"doctype": "TEX Content Translation", "property": property, "ref_doctype": doctype,
			                "ref_name": name, "field": field, "language": lang, "text": text}).insert(
				ignore_permissions=True)
			created += 1
	clear_cache(property)
	return {"created": created, "updated": updated, "deleted": deleted}
