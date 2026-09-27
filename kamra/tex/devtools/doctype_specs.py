"""DocType specifications for TEX Engine (see doctype_gen.py)."""

from kamra.tex.devtools.doctype_gen import CB, SB, TAB, F, dt, perm

# ─── permission sets (ADR-022) ─────────────────────────────────────────────
# TEX records are written ONLY through the TEX services/API, which check capability
# and hotel scope. DocType permissions therefore give business roles no write access:
# System Manager keeps platform operations, Hotel Admin reads (hotel-scoped by the
# permission hooks), master data stays readable. Generic Desk/REST writes cannot
# bypass capabilities, revision lifecycles or immutability.
SM = perm("System Manager", "full")
HA = perm("Hotel Admin", "full")
HA_RO = perm("Hotel Admin", "readonly")
COMMERCIAL = [SM, HA_RO]
# contract cost, markups and pricing policies: platform administrators only in Desk / REST; the TEX API
# serves them by price.view_cost (G-97). Their rate tables are child tables and go with the parent
COST = [SM]
# the G-97 change of COST's DocTypes (their JSON permissions): later than every earlier stamp of theirs
COST_STAMP = "2026-10-02 00:00:00.000000"
MASTER = [SM, HA_RO, perm("Revenue Manager", "readonly"), perm("Front Desk", "readonly"),
          perm("Call Center Agent", "readonly"), perm("Finance", "readonly")]
BOOKING = [SM, HA_RO]
PAYMENTS = [SM, HA_RO]
CRM = [SM, HA_RO]
PLATFORM = [SM, HA_RO]
GRANTS = [SM, HA]           # anti-escalation is enforced in the TEX Access Grant controller
READONLY_AUDIT = [perm("System Manager", "readonly"), perm("Hotel Admin", "readonly")]
IMMUTABLE_LOG = [perm("System Manager", "readonly"), HA_RO]
# pricing internals (permlevel 1: snapshots, cost, margin, FX record) are read in Desk / REST by
# platform administrators only; the TEX API serves them by price.view_cost (G-95, ADR-056)
INTERNALS = {"permlevel": 1, "read": 1, "role": "System Manager"}
INTERNALS_RW = {"permlevel": 1, "read": 1, "write": 1, "role": "System Manager"}

BOARDS = ["RO", "BB", "HB", "FB", "AI", "UAI"]
OPS_ROOM = ["ABSOLUTE", "MULTIPLY", "ADJUST_PERCENT", "PERCENT_OF", "ADD", "SUBTRACT", "INHERIT"]
OPS_OCC = ["MULTIPLY", "PERCENT_OF", "FIXED", "ABSOLUTE", "ADJUST_PERCENT", "ADD", "SUBTRACT", "INHERIT"]
OPS_ADJ = ["", "ADJUST_PERCENT", "MULTIPLY", "ADD", "SUBTRACT"]
OPS_MARKUP = ["ADJUST_PERCENT", "MULTIPLY", "ADD"]
PROMO_KINDS = ["EARLY_BOOKING", "LAST_MINUTE", "LONG_STAY", "MEMBER", "PROMO_CODE", "MARKET", "ROOM", "PACKAGE",
               "BOOKING_DATE", "STAY_DATE", "ARRIVAL", "DEPARTURE", "SPECIAL_OFFER"]
PROMO_VALUE = ["PERCENT", "FIXED_STAY", "FIXED_NIGHT", "MULTIPLIER", "FREE_NIGHTS", "VALUE_ADDED"]
STAY_MATCH = ["ANY_NIGHT", "ALL_NIGHTS", "ARRIVAL", "DEPARTURE"]
EXTRA_MODES = ["RESERVATION", "ROOM", "STAY", "PERSON", "ADULT", "CHILD", "INFANT", "NIGHT", "PERSON_NIGHT",
               "SERVICE_DATE", "UNIT", "USAGE"]
REV_STATUS = ["Draft", "Active", "Superseded", "Archived"]
# A generic decimal value — money, a percent or a factor, as its rule's op says — kept to 9 places:
# DECIMAL(21,9) (G-72, ADR-055; precision 6 made the column DECIMAL(21,6) and rounded a 7th place away).
# Loaders read it with money.db_dec; typed values are checked by commercial.decimals.check_inputs.
V = {"precision": "9"}


def revision(self_name):
	return [
		SB("Revision", collapsible=1),
		F("tex_status", "Select", "Status", REV_STATUS, default="Draft", read_only=1, in_list_view=1,
		  in_standard_filter=1),
		F("active_from", "Datetime", "Active From", read_only=1),
		F("active_to", "Datetime", "Active To", read_only=1),
		CB(),
		F("revision_no", "Int", "Revision", read_only=1, default="1"),
		F("revision_of", "Link", "Revision Of", self_name, read_only=1),
	]


def scope_links(market=True, contract=False, room=True, channel=False, property_reqd=False):
	out = [F("property", "Link", "Property", "Property", reqd=1 if property_reqd else 0, in_standard_filter=1,
	         description="" if property_reqd else "Blank = all permitted properties (global).")]
	if market:
		out.append(F("market", "Link", "Market", "TEX Market", in_standard_filter=1))
	if contract:
		out.append(F("contract", "Link", "Contract", "TEX Contract"))
	if room:
		out.append(F("room_type", "Link", "Room Type", "Room Type"))
	if channel:
		out.append(F("sales_channel", "Link", "Sales Channel", "TEX Sales Channel"))
	return out


# ═══ TEX Platform ═════════════════════════════════════════════════════════
P = "TEX Platform"
PLATFORM_SPECS = [
	dt("TEX Settings", P, [
		SB("Tenancy & navigation"),
		F("strict_tenancy", "Check", "Strict tenancy", default="1",
		  description="Users without an explicit property scope see no properties (recommended)."),
		F("show_legacy_pms", "Check", "Show legacy PMS modules",
		  description="Housekeeping, POS, laundry, banquet, night audit… hidden from TEX navigation unless on."),
		F("brand_name", "Data", "Product name", default="TEX Engine"),
		F("support_email", "Data", "Support email", options="Email"),
		CB(),
		F("default_market", "Link", "Default market", "TEX Market"),
		F("default_sales_channel", "Link", "Default sales channel", "TEX Sales Channel"),
		SB("Quotes & holds"),
		F("offer_ttl_minutes", "Int", "Offer validity (minutes)", default="20"),
		F("quote_ttl_minutes", "Int", "Quote validity (minutes)", default="30"),
		CB(),
		# K-2d: how long a booking's rooms wait for its payment, by payment method; a hotel may
		# override each (Property.tex_hold_minutes_*); services.holds.resolve_hold_minutes decides
		F("hold_minutes", "Int", "Hold duration, card payment (minutes)", default="20"),
		F("hold_minutes_link", "Int", "Hold duration, payment link (minutes)", default="1440"),
		F("hold_minutes_transfer", "Int", "Hold duration, bank transfer (minutes)", default="2880"),
		# C2: a transfer booked on the web (anyone may): shorter; the call centre and staff keep the above
		F("hold_minutes_transfer_web", "Int", "Hold duration, bank transfer booked on the web (minutes)", default="1440"),
		F("manage_link_days", "Int", "Manage-booking link validity (days)", default="365"),
		SB("Currency"),
		F("fx_provider_default", "Select", "Default FX provider", ["TCMB", "ECB", "MANUAL"], default="TCMB"),
		F("fx_max_age_days", "Int", "Max FX rate age (days)", default="4"),
		# an explicit name: SB() numbers sections globally, a new one would rename every later section
		F("section_monitoring", "Section Break", "Monitoring"),
		F("status_alert_recipients", "Small Text", "System-status alert recipients",
		  description="E-mail addresses, one per line, told when a system-status check gets worse or "
		              "recovers (ADR-047). Sent through the site's outgoing e-mail account."),
	], perms=[SM, perm("Hotel Admin", "readonly")], issingle=True,
	   extra={"modified": "2026-09-30 00:00:01.000000"}),         # the holds per payment method came later

	dt("TEX Enterprise", P, [
		F("enterprise_name", "Data", "Enterprise", reqd=1, unique=1, in_list_view=1),
		F("legal_name", "Data", "Legal name"),
		F("status", "Select", "Status", ["Active", "Suspended"], default="Active", in_list_view=1),
		CB(),
		F("country", "Link", "Country", "Country"),
		F("default_currency", "Link", "Default currency", "Currency"),
		F("notes", "Small Text", "Notes"),
	], perms=[SM, perm("Hotel Admin", "readonly")], autoname="field:enterprise_name", naming_rule="By fieldname"),

	dt("TEX Hotel Group", P, [
		F("group_name", "Data", "Hotel group", reqd=1, unique=1, in_list_view=1),
		F("enterprise", "Link", "Enterprise", "TEX Enterprise", reqd=1, in_list_view=1, in_standard_filter=1),
		CB(),
		F("default_currency", "Link", "Default currency", "Currency"),
		F("status", "Select", "Status", ["Active", "Suspended"], default="Active"),
		F("notes", "Small Text", "Notes"),
	], perms=[SM, perm("Hotel Admin", "readonly")], autoname="field:group_name", naming_rule="By fieldname"),

	dt("TEX Profile Capability", P, [
		F("capability", "Data", "Capability", reqd=1, in_list_view=1),
	], istable=True),

	# a sales channel a profile's holders may price and book on (ADR-050)
	dt("TEX Profile Channel", P, [
		F("sales_channel", "Link", "Sales channel", "TEX Sales Channel", reqd=1, in_list_view=1),
	], istable=True),

	dt("TEX Permission Profile", P, [
		F("profile_name", "Data", "Profile", reqd=1, unique=1, in_list_view=1),
		F("description", "Small Text", "Description"),
		F("is_system", "Check", "System profile", read_only=1),
		SB("Capabilities"),
		F("capabilities", "Table", "Capabilities", "TEX Profile Capability"),
		# an explicit name: SB() numbers sections globally, a new one would rename every later section
		F("section_sales_channels", "Section Break", "Sales channels"),
		F("sales_channels", "Table MultiSelect", "Sales channels", "TEX Profile Channel",
		  description="Channels this profile prices and books on. Blank = the call centre only. "
		              "The capability price.any_channel admits every channel (ADR-050)."),
	], perms=PLATFORM, autoname="field:profile_name", naming_rule="By fieldname"),

	dt("TEX Access Grant", P, [
		F("user", "Link", "User", "User", reqd=1, in_list_view=1, in_standard_filter=1),
		F("scope_level", "Select", "Scope", ["Hotel", "Hotel Group", "Enterprise", "Platform"], reqd=1,
		  default="Hotel", in_list_view=1),
		F("property", "Link", "Hotel", "Property", depends_on="eval:doc.scope_level=='Hotel'", in_list_view=1),
		F("hotel_group", "Link", "Hotel group", "TEX Hotel Group", depends_on="eval:doc.scope_level=='Hotel Group'"),
		F("enterprise", "Link", "Enterprise", "TEX Enterprise", depends_on="eval:doc.scope_level=='Enterprise'"),
		CB(),
		F("permission_profile", "Link", "Permission profile", "TEX Permission Profile", reqd=1, in_list_view=1),
		F("valid_until", "Date", "Valid until"),
		F("disabled", "Check", "Disabled"),
		F("notes", "Small Text", "Notes"),
	], perms=GRANTS, autoname="GRANT-.#####", naming_rule="Expression (old style)"),

	dt("TEX Audit Event", P, [
		F("event_time", "Datetime", "Time", in_list_view=1),
		F("action", "Data", "Action", in_list_view=1, in_standard_filter=1),
		F("actor", "Link", "Actor", "User", in_list_view=1, in_standard_filter=1),
		F("actor_roles", "Small Text", "Actor roles"),
		# how the action arrived (ADR-053, kamra.tex.security.audit.SOURCES)
		F("source", "Select", "Source", ["Desk", "API", "Guest", "Gateway Return", "System", "Webhook", "Scheduler",
		                                 "Agent"]),
		CB(),
		F("property", "Link", "Property", "Property", in_standard_filter=1),
		# an event of a hotel group or an enterprise: the hotels it reached are its TEX Audit Scope rows
		F("hotel_group", "Link", "Hotel group", "TEX Hotel Group", in_standard_filter=1),
		F("enterprise", "Link", "Enterprise", "TEX Enterprise"),
		F("reference_doctype", "Link", "Reference type", "DocType"),
		F("reference_name", "Dynamic Link", "Reference", "reference_doctype"),
		F("request_id", "Data", "Request id"),
		SB("Change"),
		F("reason", "Small Text", "Reason"),
		F("old_value", "Code", "Old value", "JSON"),
		F("new_value", "Code", "New value", "JSON"),
	], perms=READONLY_AUDIT, autoname="AUD-.YYYY.-.#######", naming_rule="Expression (old style)",
	   track_changes=False, sort_field="creation", in_create=True,
	   extra={"modified": "2026-09-26 00:00:00.000000"}),
	# the hotels an audit event of a hotel group or an enterprise reached, as it happened (ADR-053):
	# a separate record, scoped per hotel, so a hotel's staff never read the other hotels' names
	dt("TEX Audit Scope", P, [
		F("event", "Link", "Audit event", "TEX Audit Event", reqd=1, in_list_view=1, search_index=1),
		F("property", "Link", "Hotel", "Property", reqd=1, in_list_view=1, in_standard_filter=1, search_index=1),
	], perms=READONLY_AUDIT, autoname="hash", track_changes=False, sort_field="creation", in_create=True,
	   description="A hotel reached by an audit event of a hotel group or an enterprise (ADR-053).",
	   extra={"modified": "2026-09-26 00:00:00.000000"}),
]

# ═══ TEX Commercial ═══════════════════════════════════════════════════════
C = "TEX Commercial"
COMMERCIAL_SPECS = [
	dt("TEX Market", C, [
		F("market_code", "Data", "Code", reqd=1, unique=1, in_list_view=1, description="e.g. DE, UK, TR, DACH, GLOBAL"),
		F("market_name", "Data", "Name", reqd=1, in_list_view=1),
		F("is_global", "Check", "Global fallback market"),
		F("disabled", "Check", "Disabled"),
		CB(),
		F("countries", "Small Text", "Countries (ISO codes)",
		  description="Comma-separated ISO 3166-1 alpha-2 codes, e.g. DE, AT, CH"),
		F("default_currency", "Link", "Default currency", "Currency"),
		F("default_language", "Data", "Default language"),
		F("parent_market", "Link", "Parent market", "TEX Market"),
	], perms=MASTER, autoname="field:market_code", naming_rule="By fieldname", title_field="market_name"),

	dt("TEX Sales Channel", C, [
		F("channel_code", "Data", "Code", reqd=1, unique=1, in_list_view=1),
		F("channel_name", "Data", "Name", reqd=1, in_list_view=1),
		F("channel_group", "Select", "Group",
		  ["Booking Engine", "Call Center", "API", "B2B", "Metasearch", "OTA", "Other"], default="Other"),
		F("disabled", "Check", "Disabled"),
	], perms=MASTER, autoname="field:channel_code", naming_rule="By fieldname", title_field="channel_name"),

	dt("TEX Contract Channel", C, [
		F("sales_channel", "Link", "Sales channel", "TEX Sales Channel", reqd=1, in_list_view=1),
	], istable=True),

	dt("TEX Contract", C, [
		F("property", "Link", "Hotel", "Property", reqd=1, in_list_view=1, in_standard_filter=1),
		F("contract_code", "Data", "Contract code", reqd=1, in_list_view=1),
		F("contract_name", "Data", "Contract name", reqd=1, in_list_view=1),
		F("market", "Link", "Market", "TEX Market", reqd=1, in_list_view=1, in_standard_filter=1),
		CB(),
		F("status", "Select", "Status", ["Draft", "Active", "Suspended", "Archived"], default="Draft",
		  in_list_view=1, in_standard_filter=1),
		F("pricing_basis", "Select", "Pricing basis", ["PERSON", "ROOM"], default="PERSON", reqd=1),
		F("contract_currency", "Link", "Contract currency", "Currency", reqd=1),
		F("sell_currency", "Link", "Default sell currency", "Currency",
		  description="Blank = contract currency. After the first publish: the live version's (read-only)."),
		F("priority", "Int", "Priority", description="Higher wins when several contracts could sell the stay. "
		  "After the first publish: the live version's (read-only)."),
		F("is_bar", "Check", "Best Available Rate (direct contract)"),
		SB("Validity", description="Until the first publish these are edited here. Afterwards every version "
		   "carries its own sale/stay windows, channels, priority and sell currency, and these fields show the "
		   "live version's."),
		F("sale_from", "Date", "Sale from"),
		F("sale_to", "Date", "Sale to"),
		CB(),
		F("stay_from", "Date", "Stay from"),
		F("stay_to", "Date", "Stay to"),
		SB("Channels"),
		F("channels", "Table MultiSelect", "Sales channels", "TEX Contract Channel",
		  description="Blank = every channel."),
		SB("Versions"),
		F("active_version", "Link", "Active version", "TEX Contract Version", read_only=1),
		F("latest_version_no", "Int", "Latest version", read_only=1),
		CB(),
		F("notes", "Small Text", "Notes"),
	], perms=COMMERCIAL, autoname="CTR-.#####", naming_rule="Expression (old style)", title_field="contract_name",
	   search_fields="contract_code,contract_name,property,market"),

	dt("TEX Contract Room", C, [
		F("room_type", "Link", "Room type", "Room Type", reqd=1, in_list_view=1),
		F("is_base", "Check", "Base room", in_list_view=1),
		F("max_adults", "Int", "Max adults", in_list_view=1, description="0 = room type setting"),
		F("max_children", "Int", "Max children", in_list_view=1),
		F("max_occupants", "Int", "Max occupants", in_list_view=1),
		F("min_adults", "Int", "Min adults"),
		F("included_adults", "Int", "Included adults (room basis)"),
	], istable=True),

	dt("TEX Price Period", C, [
		F("period_code", "Data", "Code", reqd=1, in_list_view=1),
		F("period_name", "Data", "Name", in_list_view=1),
		F("start_date", "Date", "From", reqd=1, in_list_view=1),
		F("end_date", "Date", "To (inclusive)", reqd=1, in_list_view=1),
		F("weekdays", "Data", "Weekdays", description="Blank = every day; e.g. Fri,Sat"),
		F("adjustment_op", "Select", "Night adjustment", OPS_ADJ),
		F("adjustment_value", "Float", "Adjustment value", **V),
		F("priority", "Int", "Priority"),
	], istable=True),

	dt("TEX Period Rate", C, [
		F("room_type", "Link", "Room type", "Room Type", reqd=1, in_list_view=1),
		F("period_code", "Data", "Period", in_list_view=1, description="Blank = every period"),
		F("op", "Select", "Rule", OPS_ROOM, default="ABSOLUTE", reqd=1, in_list_view=1),
		F("value", "Float", "Value", in_list_view=1, **V),
		F("base_room_type", "Link", "Derived from", "Room Type", in_list_view=1),
	], istable=True),

	dt("TEX Occupancy Rule", C, [
		F("target", "Select", "Applies to", ["ADULT", "CHILD", "COMBINATION"], reqd=1, in_list_view=1),
		F("position", "Int", "Position", in_list_view=1, description="0 = any position"),
		F("age_band", "Data", "Age band", in_list_view=1),
		F("combination", "Data", "Combination", in_list_view=1,
		  description="adults+children, e.g. 2+1, 1+0, 2+* ; blank = any"),
		F("room_type", "Link", "Room type", "Room Type"),
		F("period_code", "Data", "Period"),
		F("op", "Select", "Rule", OPS_OCC, default="MULTIPLY", reqd=1, in_list_view=1),
		F("value", "Float", "Value", in_list_view=1, **V),
		F("is_override", "Check", "Specific override"),
		F("note", "Data", "Note"),
	], istable=True),

	dt("TEX Child Age Band", C, [
		F("band_code", "Data", "Code", reqd=1, in_list_view=1),
		F("label", "Data", "Label", in_list_view=1),
		F("from_age", "Float", "From age", in_list_view=1, precision="2"),
		F("to_age", "Float", "To age", in_list_view=1, precision="2",
		  description="2.99 or 3 both mean 'until the 3rd birthday'"),
		F("is_infant", "Check", "Infant", in_list_view=1),
	], istable=True),

	dt("TEX Board Rule", C, [
		F("board", "Select", "Board", BOARDS, reqd=1, in_list_view=1),
		F("is_base", "Check", "Included (base board)", in_list_view=1),
		F("op", "Select", "Supplement type", ["ADD", "ADJUST_PERCENT", "ABSOLUTE"], default="ADD", in_list_view=1),
		F("adult_amount", "Float", "Adult amount / %", in_list_view=1, **V),
		F("child_percent", "Percent", "Child % of adult", default="50", in_list_view=1, **V),
		F("infant_free", "Check", "Infants free", default="1"),
		F("room_type", "Link", "Room type", "Room Type"),
		F("period_code", "Data", "Period"),
		F("label", "Data", "Label"),
	], istable=True),

	dt("TEX Contract Rate Plan", C, [
		F("rate_plan", "Link", "Rate plan", "Rate Plan", reqd=1, in_list_view=1),
		F("op", "Select", "Adjustment", OPS_ADJ, in_list_view=1),
		F("value", "Float", "Value", in_list_view=1, **V),
		F("refundable", "Check", "Refundable", default="1", in_list_view=1),
		F("boards", "Data", "Boards", description="Blank = all boards; e.g. AI,UAI"),
		F("cancellation_policy", "Link", "Cancellation policy", "TEX Cancellation Policy"),
		F("payment_policy", "Link", "Payment policy", "TEX Payment Policy"),
	], istable=True),

	dt("TEX Contract Offer", C, [
		F("offer_code", "Data", "Code", reqd=1, in_list_view=1),
		F("offer_name", "Data", "Name", in_list_view=1),
		F("kind", "Select", "Kind", PROMO_KINDS, default="EARLY_BOOKING"),
		F("value_type", "Select", "Value type", PROMO_VALUE, default="PERCENT", in_list_view=1),
		F("value", "Float", "Value", in_list_view=1, **V),
		F("stage", "Select", "Applies to", ["SELL", "COST"], default="SELL"),
		F("sale_from", "Date", "Sale from"),
		F("sale_to", "Date", "Sale to"),
		F("stay_from", "Date", "Stay from"),
		F("stay_to", "Date", "Stay to"),
		F("stay_match", "Select", "Stay match", STAY_MATCH, default="ANY_NIGHT"),
		F("min_nights", "Int", "Min nights"),
		F("max_nights", "Int", "Max nights"),
		F("min_lead_days", "Int", "Min days before arrival"),
		F("max_lead_days", "Int", "Max days before arrival"),
		F("room_types", "Data", "Room types", description="Comma list; blank = all"),
		F("boards", "Data", "Boards"),
		F("stackable", "Check", "Stackable", default="1"),
		F("exclusive", "Check", "Exclusive"),
		F("priority", "Int", "Priority"),
		F("offer_group", "Data", "Incompatible group"),
		F("free_nights_stay", "Int", "Stay X"),
		F("free_nights_pay", "Int", "Pay Y"),
	], istable=True),

	dt("TEX Contract Version", C, [
		F("contract", "Link", "Contract", "TEX Contract", reqd=1, in_list_view=1, in_standard_filter=1),
		F("version_no", "Int", "Version", read_only=1, in_list_view=1),
		F("status", "Select", "Status", ["Draft", "Published", "Superseded", "Withdrawn"], default="Draft",
		  read_only=1, in_list_view=1, in_standard_filter=1),
		F("change_note", "Small Text", "Change note"),
		CB(),
		F("effective_from", "Datetime", "Sell from (effective)",
		  description="Sale time from which this version is active. Blank = when published."),
		F("published_at", "Datetime", "Published at", read_only=1),
		F("published_by", "Link", "Published by", "User", read_only=1),
		F("active_to", "Datetime", "Active until", read_only=1),
		F("based_on", "Link", "Based on", "TEX Contract Version", read_only=1),
		# selling terms (G-50, ADR-045): each version carries them and freezes them at publish;
		# explicit layout names keep the generated section/column numbering of other DocTypes
		F("selling_tab", "Tab Break", "Selling terms"),
		F("sale_from", "Date", "Sale from",
		  description="Until the contract's first publish, the contract header's values are used."),
		F("sale_to", "Date", "Sale to"),
		F("selling_column", "Column Break"),
		F("stay_from", "Date", "Stay from"),
		F("stay_to", "Date", "Stay to"),
		F("selling_section", "Section Break"),
		F("priority", "Int", "Priority", description="Higher wins when several contracts could sell the stay."),
		F("sell_currency", "Link", "Default sell currency", "Currency", description="Blank = contract currency."),
		F("channels", "Table MultiSelect", "Sales channels", "TEX Contract Channel",
		  description="Blank = every channel."),
		F("header_snapshot_section", "Section Break", "Frozen before selling terms were versioned"),
		F("header_snapshot_at", "Datetime", "Header snapshot taken", read_only=1,
		  description="Only a version frozen before selling terms were versioned: the terms above are the contract "
		              "header's at the upgrade, and the version sells only where both they and its frozen payload "
		              "allow."),
		F("header_market", "Link", "Header market at the upgrade", "TEX Market", read_only=1),
		TAB("Settings"),
		F("child_ordering", "Select", "Child order", ["OLDEST_FIRST", "YOUNGEST_FIRST", "AS_ENTERED"],
		  default="OLDEST_FIRST"),
		F("age_basis", "Select", "Age evaluated on", ["ARRIVAL", "BOOKING_DATE"], default="ARRIVAL"),
		F("children_over_max_as_adults", "Check", "Children above top band count as adults", default="1"),
		F("infants_count_as_occupants", "Check", "Infants count towards capacity", default="1"),
		# O-2 (ADR-067, D-2): 1 keeps what every version so far priced; a new contract's first draft says 0
		F("infants_count_as_children", "Check", "Infants count as children", default="1",
		  description="For combination rules and the room's maximum children. Off: infants are numbered after the "
		              "other children and never change their price."),
		CB(),
		F("prices_include_tax", "Check", "Prices include tax", default="1"),
		F("stacking", "Select", "Promotion stacking", ["SEQUENTIAL", "ADDITIVE"], default="SEQUENTIAL"),
		F("room_basis_extra_unit", "Select", "Room basis: extra person unit",
		  ["PER_PERSON_SHARE", "ROOM_PRICE"], default="PER_PERSON_SHARE"),
		F("room_basis_children_fill_included", "Check", "Room basis: children fill unused included places"),
		TAB("Rooms & periods"),
		F("rooms", "Table", "Rooms", "TEX Contract Room"),
		F("periods", "Table", "Stay periods", "TEX Price Period"),
		F("period_rates", "Table", "Room prices", "TEX Period Rate"),
		TAB("Occupancy"),
		F("age_bands", "Table", "Child age bands", "TEX Child Age Band",
		  description="Blank = inherited from the hotel/market pricing policy at publish time."),
		F("occupancy_rules", "Table", "Occupancy rules", "TEX Occupancy Rule"),
		TAB("Boards & rate plans"),
		F("boards", "Table", "Boards", "TEX Board Rule"),
		F("rate_plans", "Table", "Rate plans", "TEX Contract Rate Plan"),
		TAB("Offers"),
		F("offers", "Table", "Contract offers", "TEX Contract Offer"),
		TAB("Published payload"),
		F("payload_hash", "Data", "Payload hash", read_only=1),
		F("payload", "Code", "Frozen payload", "JSON", read_only=1),
		F("validation_report", "Code", "Validation report", "JSON", read_only=1),
	], perms=COST, autoname="hash", title_field="contract", sort_field="creation",
	   extra={"modified": COST_STAMP}),                # infants_count_as_children (O-2), then Desk/REST cost (G-97)

	dt("TEX Pricing Policy", C, [
		F("policy_name", "Data", "Policy", reqd=1, in_list_view=1),
		*scope_links(market=True, room=False),
		SB("Child age bands"),
		F("age_bands", "Table", "Age bands", "TEX Child Age Band"),
		SB("Default occupancy rules"),
		F("occupancy_rules", "Table", "Occupancy rules", "TEX Occupancy Rule"),
		*revision("TEX Pricing Policy"),
	], perms=COST, autoname="POL-.#####", naming_rule="Expression (old style)", title_field="policy_name",
	   extra={"modified": COST_STAMP}),

	dt("TEX Markup Rule", C, [
		F("label", "Data", "Label", in_list_view=1),
		*scope_links(market=True, contract=True, room=True, channel=True),
		F("stay_from", "Date", "Stay from"),
		F("stay_to", "Date", "Stay to"),
		CB(),
		F("op", "Select", "Markup type", OPS_MARKUP, default="ADJUST_PERCENT", reqd=1, in_list_view=1),
		F("value", "Float", "Value", reqd=1, in_list_view=1, **V),
		F("currency", "Link", "Currency (fixed amounts)", "Currency"),
		F("combine", "Select", "Combination", ["REPLACE", "STACK"], default="REPLACE"),
		F("priority", "Int", "Priority"),
		*revision("TEX Markup Rule"),
	], perms=COST, autoname="MKP-.#####", naming_rule="Expression (old style)", title_field="label",
	   extra={"modified": COST_STAMP}),

	dt("TEX Promotion", C, [
		F("promotion_name", "Data", "Promotion", reqd=1, in_list_view=1),
		F("property", "Link", "Hotel", "Property", in_standard_filter=1,
		  description="Blank = every hotel of the hotel group."),
		F("hotel_group", "Link", "Hotel group", "TEX Hotel Group"),
		F("kind", "Select", "Kind", PROMO_KINDS, default="SPECIAL_OFFER", in_list_view=1),
		F("trigger", "Select", "Trigger", ["Automatic", "Code"], default="Automatic", in_list_view=1),
		F("code", "Data", "Code / coupon", in_list_view=1),
		CB(),
		F("value_type", "Select", "Value type", PROMO_VALUE, default="PERCENT"),
		F("value", "Float", "Value", **V),
		F("currency", "Link", "Currency (fixed amounts)", "Currency"),
		F("stage", "Select", "Applies to price", ["SELL", "COST"], default="SELL"),
		F("applies_to", "Select", "Applies to", ["ACCOMMODATION", "EXTRAS", "TOTAL"], default="ACCOMMODATION"),
		F("value_added", "Data", "Value-added inclusion"),
		SB("Dates"),
		F("sale_from", "Date", "Sale from"),
		F("sale_to", "Date", "Sale to"),
		F("min_lead_days", "Int", "Min days before arrival"),
		F("max_lead_days", "Int", "Max days before arrival"),
		CB(),
		F("stay_from", "Date", "Stay from"),
		F("stay_to", "Date", "Stay to"),
		F("stay_match", "Select", "Stay match", STAY_MATCH, default="ANY_NIGHT"),
		F("min_nights", "Int", "Min nights"),
		F("max_nights", "Int", "Max nights"),
		SB("Eligibility"),
		F("markets", "Small Text", "Markets"),
		F("channels", "Small Text", "Sales channels"),
		F("room_types", "Small Text", "Room types"),
		CB(),
		F("boards", "Small Text", "Boards"),
		F("rate_plans", "Small Text", "Rate plans"),
		F("contracts", "Small Text", "Contracts"),
		F("requires_extras", "Small Text", "Required extras (package)"),
		F("member_only", "Check", "Members only"),
		F("min_basket", "Currency", "Minimum basket", options="currency"),
		SB("Combination & limits"),
		F("stackable", "Check", "Stackable", default="1"),
		F("exclusive", "Check", "Exclusive"),
		F("priority", "Int", "Priority"),
		F("promo_group", "Data", "Incompatible group"),
		CB(),
		F("free_nights_stay", "Int", "Stay X"),
		F("free_nights_pay", "Int", "Pay Y"),
		F("usage_limit", "Int", "Usage limit"),
		F("per_guest_limit", "Int", "Per-guest limit"),
		F("times_redeemed", "Int", "Times redeemed", read_only=1),
		F("legacy_voucher", "Link", "Legacy voucher", "Discount Voucher", read_only=1),
		*revision("TEX Promotion"),
	], perms=COMMERCIAL, autoname="PRM-.#####", naming_rule="Expression (old style)", title_field="promotion_name",
	   search_fields="promotion_name,code,property"),

	dt("TEX Promotion Redemption", C, [
		F("promotion", "Link", "Promotion", "TEX Promotion", reqd=1, in_list_view=1),
		F("code", "Data", "Code", in_list_view=1),
		F("property", "Link", "Property", "Property"),
		F("status", "Select", "Status", ["Reserved", "Committed", "Released"], default="Reserved", in_list_view=1),
		# when the use was given back: coupon usage as of a past moment counts it until then (G-51)
		F("released_at", "Datetime", "Released at"),
		CB(),
		F("booking", "Link", "Booking", "TEX Booking"),
		F("reservation", "Link", "Reservation", "Reservation"),
		F("guest_key", "Data", "Guest key (hash)"),
		F("amount", "Currency", "Discount", options="currency"),
		F("currency", "Link", "Currency", "Currency"),
	], perms=IMMUTABLE_LOG, autoname="hash", track_changes=False, sort_field="creation", in_create=True),

	dt("TEX FX Rate", C, [
		F("provider", "Select", "Provider", ["TCMB", "ECB", "MANUAL"], reqd=1, in_list_view=1,
		  in_standard_filter=1),
		F("base_currency", "Data", "Base", reqd=1, in_list_view=1, length=3),
		F("quote_currency", "Data", "Quote", reqd=1, in_list_view=1, length=3),
		F("rate_type", "Select", "Rate type", ["FOREX_SELLING", "FOREX_BUYING", "BANKNOTE_SELLING",
		                                       "BANKNOTE_BUYING", "REFERENCE"], default="FOREX_SELLING"),
		CB(),
		F("rate", "Float", "Rate", reqd=1, in_list_view=1, precision="9"),
		F("rate_date", "Date", "Rate date", reqd=1, in_list_view=1),
		F("fetched_at", "Datetime", "Fetched at"),
		F("source_ref", "Data", "Source"),
	], perms=[SM, perm("Hotel Admin", "readonly"), perm("Revenue Manager", "readonly"), perm("Finance", "readonly")],
	   autoname="hash", track_changes=False, sort_field="creation"),

	dt("TEX FX Policy", C, [
		F("property", "Link", "Hotel", "Property", description="Blank = global default."),
		F("from_currency", "Link", "From", "Currency", reqd=1, in_list_view=1),
		F("to_currency", "Link", "To", "Currency", reqd=1, in_list_view=1),
		CB(),
		F("mode", "Select", "Mode", ["PROVIDER_PERCENT", "PROVIDER", "PROVIDER_FIXED", "MANUAL"],
		  default="PROVIDER", reqd=1, in_list_view=1),
		F("provider", "Select", "Provider", ["TCMB", "ECB"], default="TCMB"),
		F("rate_type", "Select", "Rate type", ["FOREX_SELLING", "FOREX_BUYING", "BANKNOTE_SELLING",
		                                       "BANKNOTE_BUYING", "REFERENCE"], default="FOREX_SELLING"),
		F("manual_rate", "Float", "Manual rate", precision="9"),
		F("adjustment", "Float", "Adjustment (% or fixed)", **V),
		F("max_age_days", "Int", "Max rate age (days)", default="4"),
		*revision("TEX FX Policy"),
	], perms=COMMERCIAL, autoname="FXP-.#####", naming_rule="Expression (old style)"),

	dt("TEX ARI Restriction", C, [
		F("property", "Link", "Property", "Property", reqd=1, in_standard_filter=1),
		F("restriction_date", "Date", "Date", reqd=1, in_list_view=1, in_standard_filter=1),
		F("room_type", "Link", "Room type", "Room Type", in_list_view=1),
		F("contract", "Link", "Contract", "TEX Contract"),
		F("market", "Link", "Market", "TEX Market"),
		F("rate_plan", "Link", "Rate plan", "Rate Plan"),
		F("sales_channel", "Link", "Sales channel", "TEX Sales Channel"),
		# a product surface instead of one sales channel (G-48, ADR-057); never both
		F("channel_scope", "Select", "Channel scope", ["", "Booking Engine", "Call Center",
		                                               "Booking Engine + Call Center"]),
		CB(),
		F("stop_sell", "Select", "Stop sell", ["", "STOP", "OPEN"], in_list_view=1),
		F("stop_sell_mode", "Select", "Stop sell mode", ["", "STAY_THROUGH", "ARRIVAL", "DEPARTURE"]),
		F("min_los", "Int", "Min LOS", in_list_view=1),
		F("max_los", "Int", "Max LOS"),
		F("cta", "Select", "Closed to arrival", ["", "Yes", "No"]),
		F("ctd", "Select", "Closed to departure", ["", "Yes", "No"]),
		F("release_days", "Int", "Release days"),
		F("min_advance", "Int", "Min advance days"),
		F("max_advance", "Int", "Max advance days"),
		# the booking window: the sale dates on which this night is sold (G-48, ADR-057)
		F("book_from", "Date", "Bookable from (sale date)"),
		F("book_to", "Date", "Bookable until (sale date)"),
		F("scope_key", "Data", "Scope key", read_only=1, unique=1, hidden=1),
		F("note", "Data", "Note"),
	], perms=COMMERCIAL, autoname="hash", sort_field="restriction_date"),

	dt("TEX Inventory Day", C, [
		F("property", "Link", "Property", "Property", reqd=1),
		F("room_type", "Link", "Room type / pool", "Room Type", reqd=1, in_list_view=1),
		F("inventory_date", "Date", "Date", reqd=1, in_list_view=1),
		CB(),
		F("base_inventory", "Int", "Base inventory", in_list_view=1),
		F("manual_adjustment", "Int", "Manual adjustment", in_list_view=1),
		F("oversell_limit", "Int", "Oversell limit"),
		F("closed", "Check", "Closed", in_list_view=1),
		F("note", "Data", "Note"),
	], perms=COMMERCIAL, autoname="hash", sort_field="inventory_date"),

	# a capacity-limited extra on one service day (G-19): the lock row and the counter, keyed
	# by the extra's code so the capacity spans the extra's revisions
	dt("TEX Extra Inventory Day", C, [
		F("property", "Link", "Hotel", "Property", reqd=1, in_standard_filter=1),
		F("extra_code", "Data", "Extra code", reqd=1, in_list_view=1, in_standard_filter=1),
		F("service_date", "Date", "Date", reqd=1, in_list_view=1),
		CB(),
		F("capacity", "Int", "Capacity", in_list_view=1, description="0 = the extra's daily capacity"),
		F("closed", "Check", "Closed", in_list_view=1),
		F("sold", "Int", "Sold (held and confirmed units)", read_only=1, in_list_view=1),
		F("note", "Data", "Note"),
	], perms=COMMERCIAL, autoname="hash", sort_field="service_date"),

	# who holds a limited extra's units (G-19): one row per reservation, extra and day
	dt("TEX Extra Allocation", C, [
		F("property", "Link", "Hotel", "Property", reqd=1, in_standard_filter=1),
		F("extra_code", "Data", "Extra code", reqd=1, in_list_view=1, in_standard_filter=1),
		F("extra", "Link", "Extra (revision that priced it)", "TEX Extra"),
		F("service_date", "Date", "Date", reqd=1, in_list_view=1),
		F("units", "Int", "Units", reqd=1, in_list_view=1),
		F("status", "Select", "Status", ["Held", "Confirmed", "Released"], default="Held", in_list_view=1,
		  in_standard_filter=1),
		CB(),
		F("booking", "Link", "Booking", "TEX Booking"),
		F("reservation", "Link", "Reservation", "Reservation", reqd=1),
		F("released_at", "Datetime", "Released at"),
		F("release_reason", "Data", "Release reason"),
	], perms=IMMUTABLE_LOG, autoname="hash", track_changes=False, sort_field="creation", in_create=True),

	dt("TEX Allotment", C, [
		F("property", "Link", "Property", "Property", reqd=1, in_standard_filter=1),
		F("room_type", "Link", "Room type", "Room Type", reqd=1, in_list_view=1),
		F("contract", "Link", "Contract", "TEX Contract", reqd=1, in_list_view=1),
		F("market", "Link", "Market", "TEX Market"),
		CB(),
		F("date_from", "Date", "From", reqd=1, in_list_view=1),
		F("date_to", "Date", "To", reqd=1, in_list_view=1),
		F("rooms", "Int", "Rooms per night", reqd=1, in_list_view=1),
		# two deadlines, in days before each night (G-49, ADR-048)
		F("release_days", "Int", "Release days",
		  description="Unsold rooms go back to general sale this many days before each night."),
		F("cutoff_days", "Int", "Cutoff days",
		  description="The contract stops selling this many days before each night (0 = no cutoff)."),
		F("guaranteed", "Check", "Guaranteed (withheld until release)"),
		F("disabled", "Check", "Disabled"),
		F("note", "Data", "Note"),
	], perms=COMMERCIAL, autoname="ALT-.#####", naming_rule="Expression (old style)"),

	dt("TEX Cancellation Rule", C, [
		F("days_before_arrival", "Int", "Days before arrival", in_list_view=1,
		  description="Penalty applies when cancelling fewer than this many days before arrival"),
		F("penalty_type", "Select", "Penalty", ["PERCENT", "NIGHTS", "FIXED"], default="PERCENT", in_list_view=1),
		F("penalty_value", "Float", "Value", in_list_view=1, **V),
	], istable=True),

	dt("TEX Cancellation Policy", C, [
		F("policy_name", "Data", "Policy", reqd=1, in_list_view=1),
		F("property", "Link", "Hotel", "Property", in_standard_filter=1),
		F("refundable", "Check", "Refundable", default="1", in_list_view=1),
		CB(),
		F("no_show_type", "Select", "No-show penalty", ["PERCENT", "NIGHTS", "FIXED"], default="NIGHTS"),
		F("no_show_value", "Float", "No-show value", default="1", **V),
		# the fixed amounts' currency (ADR-067, D-1): frozen with a policy that has one
		F("currency", "Link", "Currency (fixed amounts)", "Currency",
		  description="Currency of the fixed penalties; empty: the contract's currency"),
		SB("Rules"),
		F("rules", "Table", "Rules", "TEX Cancellation Rule"),
		F("description", "Small Text", "Guest-facing text"),
	], perms=COMMERCIAL, autoname="CXP-.#####", naming_rule="Expression (old style)", title_field="policy_name",
	   extra={"modified": "2026-10-01 00:00:00.000000"}),                # currency came later (ADR-067)

	dt("TEX Payment Policy", C, [
		F("policy_name", "Data", "Policy", reqd=1, in_list_view=1),
		F("property", "Link", "Hotel", "Property", in_standard_filter=1),
		F("deposit_type", "Select", "Pay now", ["NONE", "PERCENT", "NIGHTS", "FULL", "FIXED"], default="FULL",
		  in_list_view=1),
		F("deposit_value", "Float", "Value", **V),
		# the fixed deposit's currency (ADR-067, D-1): frozen with a policy that has one
		F("currency", "Link", "Currency (fixed amounts)", "Currency",
		  description="Currency of a fixed deposit; empty: the contract's currency"),
		CB(),
		F("balance_due_days", "Int", "Balance due (days before arrival)"),
		F("allow_pay_at_hotel", "Check", "Balance payable at hotel"),
		F("description", "Small Text", "Guest-facing text"),
	], perms=COMMERCIAL, autoname="PAYP-.#####", naming_rule="Expression (old style)", title_field="policy_name",
	   extra={"modified": "2026-10-01 00:00:00.000000"}),                # currency came later (ADR-067)

	dt("TEX Extra Price Rule", C, [
		F("market", "Link", "Market", "TEX Market", in_list_view=1),
		F("room_type", "Link", "Room type", "Room Type"),
		F("sales_channel", "Link", "Channel", "TEX Sales Channel"),
		F("stay_from", "Date", "Stay from"),
		F("stay_to", "Date", "Stay to"),
		F("sale_from", "Date", "Sale from"),
		F("sale_to", "Date", "Sale to"),
		F("service_from", "Date", "Service from", in_list_view=1),
		F("service_to", "Date", "Service to", in_list_view=1),
		F("amount", "Currency", "Amount", options="currency", in_list_view=1),
		F("custom_child_amounts", "Check", "Custom child/infant amounts"),
		F("child_amount", "Currency", "Child amount", options="currency"),
		F("infant_amount", "Currency", "Infant amount", options="currency"),
		F("priority", "Int", "Priority"),
	], istable=True),

	dt("TEX Extra", C, [
		F("property", "Link", "Hotel", "Property", reqd=1, in_standard_filter=1),
		F("extra_code", "Data", "Code", reqd=1, in_list_view=1),
		F("extra_name", "Data", "Name", reqd=1, in_list_view=1),
		F("category", "Select", "Category", ["Transfer", "Dining", "Spa", "Room", "Package", "Celebration",
		                                     "Excursion", "Service", "Other"], default="Service", in_list_view=1),
		F("description", "Small Text", "Description"),
		F("image", "Attach Image", "Image"),
		CB(),
		F("pricing_mode", "Select", "Pricing mode", EXTRA_MODES, default="UNIT", reqd=1, in_list_view=1),
		F("currency", "Link", "Currency", "Currency", reqd=1),
		F("amount", "Currency", "Price (adult / unit)", options="currency", in_list_view=1),
		F("child_pricing", "Select", "Child price", ["SAME_AS_ADULT", "CUSTOM"], default="SAME_AS_ADULT"),
		F("child_amount", "Currency", "Child price", options="currency", depends_on="eval:doc.child_pricing=='CUSTOM'"),
		F("infant_pricing", "Select", "Infant price", ["SAME_AS_CHILD", "FREE", "CUSTOM"], default="FREE"),
		F("infant_amount", "Currency", "Infant price", options="currency",
		  depends_on="eval:doc.infant_pricing=='CUSTOM'"),
		F("tax_category", "Select", "Tax category", ["SERVICE", "FOOD", "TRANSFER", "ACCOMMODATION"],
		  default="SERVICE"),
		SB("Availability"),
		F("is_mandatory", "Check", "Mandatory"),
		F("bookable_online", "Check", "Bookable online", default="1"),
		F("bookable_after_booking", "Check", "Bookable after booking", default="1"),
		F("order_cutoff_hours", "Int", "Order cut-off (hours)",
		  description="Added after booking: at least this many hours before the day it is used (0 = until that day)"),
		F("max_quantity", "Int", "Max quantity"),
		F("inventory_tracked", "Check", "Limited inventory"),
		F("daily_capacity", "Int", "Daily capacity", depends_on="eval:doc.inventory_tracked"),
		CB(),
		F("sale_from", "Date", "Sale from"),
		F("sale_to", "Date", "Sale to"),
		F("service_from", "Date", "Service from"),
		F("service_to", "Date", "Service to"),
		F("markets", "Small Text", "Markets"),
		F("channels", "Small Text", "Sales channels"),
		F("room_types", "Small Text", "Room types"),
		F("disabled", "Check", "Disabled"),
		SB("Price rules"),
		F("price_rules", "Table", "Price rules", "TEX Extra Price Rule"),
		F("legacy_experience", "Link", "Legacy experience", "Experience", read_only=1),
		*revision("TEX Extra"),
	], perms=COMMERCIAL, autoname="EXT-.#####", naming_rule="Expression (old style)", title_field="extra_name",
	   search_fields="extra_code,extra_name,property"),

	# a hotel's tax rules, effective-dated (G-20): pricing at sale time T uses the policy live at T
	dt("TEX Tax Policy", C, [
		F("policy_name", "Data", "Policy", reqd=1, in_list_view=1),
		F("property", "Link", "Hotel", "Property", reqd=1, in_standard_filter=1, in_list_view=1),
		F("currency", "Link", "Currency of fixed amounts", "Currency",
		  description="Fixed levies are charged in this currency, converted at the sale time's FX"),
		F("description", "Small Text", "Description"),
		SB("Tax rules"),
		F("rules", "Table", "Tax rules", "TEX Tax Rule"),
		*revision("TEX Tax Policy"),
	], perms=COMMERCIAL, autoname="TXP-.#####", naming_rule="Expression (old style)", title_field="policy_name"),

	dt("TEX Tax Rule", C, [
		F("code", "Data", "Code", reqd=1, in_list_view=1),
		F("tax_name", "Data", "Name", in_list_view=1),
		F("kind", "Select", "Kind", ["PERCENT", "PER_PERSON_NIGHT", "PER_ROOM_NIGHT"], default="PERCENT",
		  in_list_view=1),
		F("rate", "Percent", "Rate %", in_list_view=1, **V),
		F("amount", "Currency", "Fixed amount", options="currency"),
		F("applies_to", "Data", "Applies to", default="ACCOMMODATION",
		  description="ACCOMMODATION, EXTRA:*, EXTRA:FOOD … comma separated"),
		F("compound", "Check", "Compound"),
		F("sort_order", "Int", "Order"),
	], istable=True),
]

# ═══ TEX Booking ══════════════════════════════════════════════════════════
B = "TEX Booking"
BOOKING_SPECS = [
	dt("TEX Booking Room", B, [
		F("reservation", "Link", "Reservation", "Reservation", in_list_view=1),
		F("room_type", "Link", "Room type", "Room Type", in_list_view=1),
		F("check_in", "Date", "Check-in", in_list_view=1),
		F("check_out", "Date", "Check-out", in_list_view=1),
		F("adults", "Int", "Adults", in_list_view=1),
		F("children", "Int", "Children", in_list_view=1),
		F("amount", "Currency", "Amount", in_list_view=1),
		F("status", "Data", "Status"),
		F("quote", "Link", "Quote", "TEX Quote"),
	], istable=True),

	dt("TEX Booking", B, [
		F("property", "Link", "Hotel", "Property", reqd=1, in_list_view=1, in_standard_filter=1),
		F("status", "Select", "Status", ["Draft", "Held", "Pending Payment", "Confirmed", "Partially Cancelled",
		                                 "Cancelled"], default="Draft", in_list_view=1, in_standard_filter=1),
		F("sales_channel", "Link", "Sales channel", "TEX Sales Channel", in_standard_filter=1),
		F("market", "Link", "Market", "TEX Market", in_standard_filter=1),
		F("created_via", "Select", "Created via", ["Booking Engine", "Call Center", "API", "Desk", "Self Service",
		                                           "Channel"], default="Desk"),
		F("sale_at", "Datetime", "Sold at"),
		F("channel_connection", "Link", "Channel connection", "TEX Integration Connection", read_only=1),
		F("external_ref", "Data", "Channel booking id", read_only=1, in_standard_filter=1),
		CB(),
		F("booker_guest", "Link", "Booker", "Guest"),
		F("booker_name", "Data", "Booker name", in_list_view=1),
		F("booker_email", "Data", "Booker email", options="Email"),
		F("booker_phone", "Data", "Booker phone"),
		F("language", "Data", "Language"),
		SB("Money"),
		F("currency", "Link", "Currency", "Currency"),
		F("total_amount", "Currency", "Total", options="currency", in_list_view=1),
		F("paid_amount", "Currency", "Paid", options="currency", read_only=1),
		F("balance_amount", "Currency", "Balance", options="currency", read_only=1),
		CB(),
		F("payment_status", "Select", "Payment status", ["Unpaid", "Partially Paid", "Paid", "Refunded",
		                                                  "Pay at Hotel"], default="Unpaid", in_standard_filter=1),
		F("payment_method", "Data", "Payment method"),
		F("amount_due_now", "Currency", "Due now", options="currency"),
		# K-2a: a payment attempt started within the hold keeps the rooms until then, never longer
		F("payment_attempt_until", "Datetime", "Payment attempt open until", read_only=1),
		SB("Rooms"),
		F("rooms", "Table", "Rooms", "TEX Booking Room"),
		SB("Service"),
		F("guest_change_pending", "Check", "Guest change awaiting staff", in_standard_filter=1),
		F("notes", "Small Text", "Notes"),
		F("source", "Data", "Source / campaign"),
		CB(),
		F("confirmation_sent_at", "Datetime", "Confirmation sent", read_only=1),
		F("idempotency_key", "Data", "Idempotency key", read_only=1),
		F("manage_token_hash", "Data", "Manage token (hash)", read_only=1, hidden=1),
		F("manage_token_expires", "Datetime", "Manage link expires", read_only=1),
		F("booking_site", "Link", "Booking site", "TEX Booking Site"),
	], perms=BOOKING, autoname="TEX-.YYYY.-.#####", naming_rule="Expression (old style)", title_field="booker_name",
	   search_fields="booker_name,booker_email,property,status",
	   extra={"modified": "2026-09-30 00:00:00.000000"}),         # payment_attempt_until came later (K-2a)

	dt("TEX Quote", B, [
		F("property", "Link", "Hotel", "Property", in_list_view=1),
		F("status", "Select", "Status", ["Open", "Used", "Expired"], default="Open", in_list_view=1),
		F("sales_channel", "Link", "Sales channel", "TEX Sales Channel"),
		F("market", "Link", "Market", "TEX Market"),
		F("currency", "Link", "Currency", "Currency"),
		F("total_amount", "Currency", "Total", options="currency", in_list_view=1),
		CB(),
		F("contract_version", "Link", "Contract version", "TEX Contract Version"),
		F("payload_hash", "Data", "Payload hash"),
		F("expires_at", "Datetime", "Expires", in_list_view=1),
		F("booking", "Link", "Booking", "TEX Booking"),
		F("session_hash", "Data", "Session (hash)"),
		F("offer_hash", "Data", "Offer (hash)"),
		SB("Content"),
		F("request_json", "Code", "Request", "JSON"),
		F("result_json", "Long Text", "Result", permlevel=1),          # pricing internals (G-95, ADR-056)
	], perms=[*IMMUTABLE_LOG, INTERNALS], autoname="hash", track_changes=False, sort_field="creation",
	   in_create=True),

	dt("TEX Reservation Revision", B, [
		F("reservation", "Link", "Reservation", "Reservation", reqd=1, in_list_view=1, in_standard_filter=1),
		F("booking", "Link", "Booking", "TEX Booking"),
		F("revision_no", "Int", "Revision", in_list_view=1),
		F("change_type", "Select", "Change", ["Original", "Dates", "Room", "Occupancy", "Board", "Market",
		                                      "Extras", "Discount", "Price Override", "Sale Date", "Cancellation",
		                                      "Guest Request", "Multiple"], in_list_view=1),
		F("source", "Select", "Source", ["Desk", "Call Center", "Guest", "API", "System", "Channel"]),
		CB(),
		F("actor", "Link", "Actor", "User", in_list_view=1),
		F("actor_roles", "Small Text", "Actor roles"),
		F("approval_status", "Select", "Approval", ["Not Required", "Pending", "Approved", "Rejected"],
		  default="Not Required"),
		F("approved_by", "Link", "Approved by", "User"),
		F("approved_at", "Datetime", "Approved at"),
		SB("Money"),
		F("currency", "Link", "Currency", "Currency"),
		F("old_amount", "Currency", "Old amount", options="currency", in_list_view=1),
		F("new_amount", "Currency", "New amount", options="currency", in_list_view=1),
		F("difference", "Currency", "Difference", options="currency", in_list_view=1),
		CB(),
		F("pricing_basis", "Select", "Pricing basis", ["ORIGINAL_VERSION", "ORIGINAL_SALE_DATE",
		                                               "HISTORICAL_SALE_DATE", "CURRENT", "MANUAL", "NONE",
		                                               "ADD_ON", "EXTERNAL"]),
		F("basis_sale_at", "Datetime", "Basis sale time"),
		F("override_amount", "Currency", "Manual override", options="currency"),
		F("reason", "Small Text", "Reason"),
		SB("Detail"),
		F("changes_json", "Code", "Field changes", "JSON"),
		F("snapshot_before", "Long Text", "Pricing before", permlevel=1),     # pricing internals (G-95, ADR-056)
		F("snapshot_after", "Long Text", "Pricing after", permlevel=1),
	], perms=[*IMMUTABLE_LOG, INTERNALS], autoname="REV-.######", naming_rule="Expression (old style)", track_changes=False,
	   sort_field="creation", in_create=True),

	# a guest's own change and how its money was settled (G-45, ADR-044): written only by
	# services.guest_changes; the proposal, the totals and the amount to collect never change.
	# Its layout breaks are named here, not numbered by SB()/CB(), so the generated names of
	# every DocType after it stay as they were
	dt("TEX Guest Change Request", B, [
		F("property", "Link", "Hotel", "Property", reqd=1, in_list_view=1, in_standard_filter=1),
		F("booking", "Link", "Booking", "TEX Booking", reqd=1, in_list_view=1, search_index=1),
		F("reservation", "Link", "Reservation", "Reservation", reqd=1, in_list_view=1, search_index=1),
		F("status", "Select", "Status", ["Awaiting Payment", "Applied", "Requested", "Approved", "Rejected", "Failed",
		                                 "Expired", "Superseded"], reqd=1, in_list_view=1, in_standard_filter=1, search_index=1),
		F("gcr_column_1", "Column Break"),
		F("proposal_hash", "Data", "Proposal (hash)", unique=1, read_only=1, hidden=1),
		F("proposal", "Long Text", "Proposal (JSON)", read_only=1,
		  description="The signed proposal the guest accepted, with its pricing sale time"),
		F("note", "Small Text", "Guest note"),
		F("expires_at", "Datetime", "Payment deadline", read_only=1,
		  description="The accepted price is honoured for a payment arriving until then"),
		F("gcr_section_money", "Section Break", "Money"),
		F("currency", "Link", "Currency", "Currency"),
		F("old_total", "Currency", "Booking total before", options="currency"),
		F("new_total", "Currency", "Booking total after", options="currency"),
		F("difference", "Currency", "Difference", options="currency", in_list_view=1),
		F("gcr_column_2", "Column Break"),
		F("collect_amount", "Currency", "To pay online first", options="currency"),
		F("payment_transaction", "Link", "Payment", "TEX Payment Transaction"),
		F("attempt", "Int", "Payment attempts"),
		F("gcr_section_settlement", "Section Break", "Settlement"),
		F("settlement", "Select", "Settlement", ["", "None", "Online payment", "Pay at hotel", "Balance", "Refund",
		                                         "Credit on booking", "Staff"], in_list_view=1, in_standard_filter=1),
		F("settlement_amount", "Currency", "Settlement amount", options="currency"),
		F("refunded_amount", "Currency", "Refunded", options="currency"),
		F("settle_pending", "Check", "Refund queued", read_only=1),
		# money of this change that waits for staff (review follow-up of ADR-044): a refund TEX
		# cannot make, or one whose outcome the gateway never confirmed
		F("staff_open", "Check", "Money waits for staff", read_only=1, in_standard_filter=1),
		F("staff_amount", "Currency", "For staff to settle", options="currency", read_only=1),
		F("staff_reason", "Select", "Why staff", ["", "Refund by staff", "Verify refund at gateway"], read_only=1),
		F("unknown_refund", "Link", "Refund to verify", "TEX Payment Transaction", read_only=1,
		  description="A refund the gateway did not confirm: check it at the gateway before refunding again"),
		# second review of ADR-044: the refund being made (on record, with the refund, before the
		# gateway is asked), the payments already given back or left to staff, the run that holds
		# the refunds (one at a time) and whether the rate's cancellation terms applied
		F("refund_in_flight", "Link", "Refund being made", "TEX Payment Transaction", read_only=1),
		# third review: every refund the request made (what it refunded is counted from them) and
		# how much of the money left to staff they already settled
		F("refund_rows", "Small Text", "Refunds made", read_only=1),
		F("staff_settled", "Currency", "Settled by staff", options="currency", read_only=1),
		F("returned_charges", "Small Text", "Payments given back", read_only=1,
		  description="Payments of this change that were given back, or left to staff to give back"),
		F("settle_claim", "Data", "Refund run", read_only=1, hidden=1),
		F("settle_claimed_until", "Datetime", "Refund run until", read_only=1, hidden=1),
		F("penalty_terms", "Check", "Inside the rate's cancellation terms", read_only=1,
		  description="Asked while cancelling would cost a fee: the hotel approves it"),
		F("gcr_column_3", "Column Break"),
		F("revision", "Link", "Revision", "TEX Reservation Revision"),
		F("error", "Small Text", "Why it was not applied"),
		F("resolved_by", "Link", "Resolved by", "User"),
		F("resolved_at", "Datetime", "Resolved at"),
		F("resolution", "Small Text", "Staff note"),
	], perms=IMMUTABLE_LOG, autoname="GCR-.YYYY.-.#####", naming_rule="Expression (old style)",
	   sort_field="creation", in_create=True,
	   # the staff fields, then the refund-run fields, then the refunds made, came after the first
	   # migration: a newer stamp makes migrate load them
	   extra={"modified": "2026-09-28 00:00:00.000000"}),

	dt("TEX Booking Domain", B, [
		F("domain", "Data", "Domain", reqd=1, in_list_view=1,
		  description="A host name such as book.hotel.com, pointed at TEX (ADR-035)"),
		F("is_primary", "Check", "Primary", in_list_view=1,
		  description="Used in guest e-mails, payment links and return pages"),
		F("verified", "Check", "Verified", read_only=1, in_list_view=1),
		F("verification_token", "Data", "Verification token", read_only=1),
		F("verified_at", "Datetime", "Verified at", read_only=1),
		F("last_checked_at", "Datetime", "Last checked", read_only=1),
		F("check_failures", "Int", "Failed checks in a row", read_only=1),
	], istable=True),

	dt("TEX Booking Site", B, [
		F("site_name", "Data", "Site name", reqd=1, in_list_view=1),
		F("site_slug", "Data", "Slug", reqd=1, unique=1, in_list_view=1),
		F("enabled", "Check", "Enabled", default="1", in_list_view=1),
		F("property", "Link", "Hotel", "Property", description="Single-hotel site"),
		F("hotel_group", "Link", "Hotel group", "TEX Hotel Group", description="Group site (multi-hotel search)"),
		CB(),
		F("default_language", "Data", "Default language", default="en"),
		F("languages", "Small Text", "Languages", default="en,tr,de,ru,ro,pl"),
		F("default_currency", "Link", "Default currency", "Currency"),
		F("currencies", "Small Text", "Currencies"),
		F("default_market", "Link", "Default market", "TEX Market"),
		F("sales_channel", "Link", "Sales channel", "TEX Sales Channel"),
		F("self_service_enabled", "Check", "Guest self-service", default="1"),
		TAB("Branding"),
		F("logo", "Attach Image", "Logo"),
		F("primary_color", "Data", "Primary colour", default="#0B3B5B"),
		F("accent_color", "Data", "Accent colour", default="#C8963E"),
		F("background_color", "Data", "Background", default="#F7F7F5"),
		F("font_family", "Select", "Font", ["Inter", "DM Sans", "Nunito Sans", "Source Sans 3", "Lora",
		                                    "Playfair Display", "System"], default="Inter"),
		CB(),
		F("radius", "Select", "Corner radius", ["none", "sm", "md", "lg", "xl"], default="md"),
		F("card_radius", "Select", "Card radius", ["none", "sm", "md", "lg", "xl"], default="lg"),
		F("button_style", "Select", "Buttons", ["solid", "outline", "pill"], default="solid"),
		F("header_layout", "Select", "Header", ["left", "center", "split"], default="left"),
		F("search_style", "Select", "Search bar", ["inline", "card", "overlay"], default="card"),
		F("hero_image", "Attach Image", "Hero image"),
		TAB("Content"),
		F("contact_phone", "Data", "Phone"),
		F("contact_email", "Data", "Email", options="Email"),
		F("whatsapp", "Data", "WhatsApp"),
		F("address", "Small Text", "Address"),
		CB(),
		F("custom_texts", "Code", "Custom texts (per language)", "JSON"),
		F("policies", "Text", "Policies"),
		TAB("Embed & domains"),
		F("allowed_embed_origins", "Small Text", "Allowed embed origins",
		  description="One origin per line, e.g. https://www.hotel.com"),
		F("widget_mode", "Select", "Widget default", ["search", "button", "modal", "redirect"], default="search"),
		F("domains", "Table", "Custom domains", "TEX Booking Domain"),
		TAB("Analytics"),
		F("ga4_measurement_id", "Data", "GA4 measurement id"),
		F("gtm_container_id", "Data", "GTM container id"),
		F("meta_pixel_id", "Data", "Meta pixel id"),
		F("consent_banner", "Check", "Show consent banner", default="1"),
	], perms=[SM, HA_RO],
	   autoname="field:site_slug", naming_rule="By fieldname", title_field="site_name"),

	dt("TEX Content Translation", B, [
		F("property", "Link", "Hotel", "Property", reqd=1, in_list_view=1, in_standard_filter=1),
		F("ref_doctype", "Select", "Record type", ["Room Type", "Rate Plan", "TEX Extra", "Property",
		                                            "TEX Cancellation Policy", "TEX Payment Policy"],
		  reqd=1, in_list_view=1, in_standard_filter=1),
		F("ref_name", "Dynamic Link", "Record", "ref_doctype", reqd=1, in_list_view=1),
		F("field", "Data", "Field", reqd=1, in_list_view=1),
		F("language", "Select", "Language", ["tr", "en", "de", "ru", "ro", "pl"], reqd=1, in_list_view=1,
		  in_standard_filter=1),
		F("text", "Text", "Text", reqd=1),
	], perms=BOOKING, autoname="hash", title_field="ref_name",
	   description="Guest-facing text of a hotel record in one language (written through the TEX API)."),

	dt("TEX Funnel Event", B, [
		F("event", "Select", "Event", ["search", "room_view", "quote", "guest_details", "payment_started",
		                               "abandoned", "booked"], reqd=1, in_list_view=1, in_standard_filter=1),
		F("occurred_at", "Datetime", "At", in_list_view=1),
		F("site", "Link", "Site", "TEX Booking Site"),
		F("property", "Link", "Property", "Property", in_standard_filter=1),
		CB(),
		# who the visitor is, and what leads to them: withheld from Desk / REST (ADR-056 reviews)
		F("session_id", "Data", "Session", permlevel=1),
		F("guest", "Link", "Guest", "Guest", permlevel=1),
		F("email_hash", "Data", "Email (hash)", permlevel=1),
		F("consent_marketing", "Check", "Marketing consent"),
		F("value", "Currency", "Value", options="currency"),
		F("currency", "Link", "Currency", "Currency"),
		F("payload", "Code", "Payload", "JSON", permlevel=1),
	], perms=[*READONLY_AUDIT, INTERNALS], autoname="hash", track_changes=False,
	   sort_field="creation", in_create=True),
]

# ═══ TEX Payments ═════════════════════════════════════════════════════════
PM = "TEX Payments"
PROVIDERS = ["Mock", "iyzico", "Sipay", "Virtual POS", "Bank Transfer", "Pay at Hotel"]
PAYMENT_SPECS = [
	dt("TEX Payment Provider Account", PM, [
		F("label", "Data", "Label", reqd=1, in_list_view=1),
		F("property", "Link", "Hotel", "Property", in_standard_filter=1),
		F("provider", "Select", "Provider", PROVIDERS, reqd=1, in_list_view=1),
		F("environment", "Select", "Environment", ["Sandbox", "Production"], default="Sandbox", in_list_view=1),
		F("enabled", "Check", "Enabled", default="1", in_list_view=1),
		F("currencies", "Small Text", "Currencies", description="Blank = any"),
		SB("Credentials", depends_on="eval:!['Bank Transfer','Pay at Hotel','Mock'].includes(doc.provider)"),
		F("api_key", "Password", "API key / merchant id", description="Stored encrypted; never shown again (G-83)"),
		F("secret_key", "Password", "Secret key"),
		F("merchant_key", "Password", "Merchant key"),
		CB(),
		F("terminal_id", "Data", "Terminal / client id"),
		F("store_key", "Password", "3D store key"),
		F("bank_code", "Select", "Virtual POS bank / platform", ["", "NestPay", "Garanti", "YKB PosNet",
		                                                          "Vakif", "Kuveyt"]),
		F("gateway_url", "Data", "Gateway URL override"),
		F("webhook_secret", "Password", "Webhook secret"),
		SB("Bank transfer", depends_on="eval:doc.provider=='Bank Transfer'"),
		F("bank_name", "Data", "Bank"),
		F("iban", "Data", "IBAN"),
		F("account_holder", "Data", "Account holder"),
		F("transfer_instructions", "Small Text", "Instructions"),
	], perms=[SM, HA_RO], autoname="PPA-.####", naming_rule="Expression (old style)",
	   title_field="label"),

	dt("TEX Payment Method Rule", PM, [
		F("property", "Link", "Hotel", "Property", reqd=1, in_list_view=1),
		F("method", "Select", "Method", ["Card", "Bank Transfer", "Pay at Hotel"], reqd=1, in_list_view=1),
		F("provider_account", "Link", "Provider account", "TEX Payment Provider Account", in_list_view=1),
		CB(),
		F("market", "Link", "Market", "TEX Market", in_list_view=1),
		F("currency", "Link", "Currency", "Currency"),
		F("sales_channel", "Link", "Sales channel", "TEX Sales Channel"),
		F("priority", "Int", "Priority"),
		F("disabled", "Check", "Disabled"),
	], perms=[SM, HA_RO],
	   autoname="PMR-.#####", naming_rule="Expression (old style)"),

	dt("TEX Payment Link", PM, [
		F("property", "Link", "Hotel", "Property", reqd=1, in_standard_filter=1),
		F("status", "Select", "Status", ["Draft", "Active", "Partially Paid", "Paid", "Expired", "Cancelled"],
		  default="Active", in_list_view=1, in_standard_filter=1, read_only=1),
		F("amount", "Currency", "Amount", options="currency", reqd=1, in_list_view=1),
		F("currency", "Link", "Currency", "Currency", reqd=1),
		F("description", "Small Text", "Description"),
		F("expires_at", "Datetime", "Expires"),
		CB(),
		F("provider_account", "Link", "Provider account", "TEX Payment Provider Account"),
		F("booking", "Link", "Booking", "TEX Booking"),
		F("reservation", "Link", "Reservation", "Reservation"),
		F("guest_name", "Data", "Guest name", in_list_view=1),
		F("guest_email", "Data", "Guest email", options="Email"),
		SB("Settlement"),
		F("paid_amount", "Currency", "Paid", options="currency", read_only=1),
		F("allocated_amount", "Currency", "Allocated", options="currency", read_only=1),
		F("public_url", "Data", "Payment URL", read_only=1),
		CB(),
		F("token_hash", "Data", "Token (hash)", read_only=1, hidden=1),
		# one link per key, in the database (O-38, p57)
		F("idempotency_key", "Data", "Idempotency key", read_only=1, unique=1),
	], perms=[SM, HA_RO],
	   autoname="PL-.YYYY.-.#####", naming_rule="Expression (old style)", title_field="guest_name"),

	dt("TEX Payment Transaction", PM, [
		F("property", "Link", "Hotel", "Property", in_standard_filter=1),
		F("txn_type", "Select", "Type", ["Charge", "Refund", "Void"], in_list_view=1, in_standard_filter=1),
		F("status", "Select", "Status", ["Pending", "Succeeded", "Failed", "Cancelled"], in_list_view=1,
		  in_standard_filter=1),
		F("method", "Select", "Method", ["Card", "Bank Transfer", "Pay at Hotel", "Payment Link", "Manual"]),
		F("amount", "Currency", "Amount", options="currency", in_list_view=1),
		F("currency", "Link", "Currency", "Currency"),
		CB(),
		F("provider_account", "Link", "Provider account", "TEX Payment Provider Account"),
		F("provider", "Data", "Provider"),
		F("provider_ref", "Data", "Provider reference"),
		F("idempotency_key", "Data", "Idempotency key", unique=1),
		# indexed: the refunds of a payment are read with a locking read under its lock (the
		# amounts deciding what may still be refunded), which must lock only them (G-45 re-review 4)
		F("parent_transaction", "Link", "Original transaction", "TEX Payment Transaction", search_index=1),
		SB("Links"),
		F("payment_link", "Link", "Payment link", "TEX Payment Link"),
		F("booking", "Link", "Booking", "TEX Booking", search_index=1),
		F("reservation", "Link", "Reservation", "Reservation"),
		CB(),
		F("card_brand", "Data", "Card brand"),
		F("card_last4", "Data", "Card last 4", length=4),
		F("actor", "Link", "Actor", "User"),
		F("completed_at", "Datetime", "Completed at"),
		# K-2a: a pending charge of a booking is a payment in flight only until then
		F("expires_at", "Datetime", "Attempt open until", read_only=1),
		# B4: when the gateway captured the money, by its own clock (when it states it): a payment is
		# late by this, never by when its news reached TEX
		F("captured_at", "Datetime", "Captured at (gateway)", read_only=1),
		# NEW-6 (ADR-066): a start is asking the gateway for its checkout since then, with no lock held; a
		# second start of the charge waits until it is cleared or older than the lease (p68)
		F("checkout_started_at", "Datetime", "Checkout being started since", read_only=1),
		SB("Outcome"),
		F("raw_status", "Data", "Provider status"),
		F("error_code", "Data", "Error code"),
		F("error_message", "Small Text", "Error"),
		F("reason", "Small Text", "Reason"),
		F("return_url", "Small Text", "Return URL", read_only=1),
		# K-2b: money the gateway captured that could not safely confirm its booking (its hold was
		# over, or its rooms were gone): recorded, kept off the booking, until refunded or resolved
		# an explicit name: SB() numbers sections globally, a new one would rename every later section
		F("section_reconciliation", "Section Break", "Reconciliation"),
		F("reconciliation", "Select", "Reconciliation", ["", "Action Required", "Refund Queued", "Refunded",
		                                                 "Resolved"], read_only=1, in_standard_filter=1),
		F("reconciliation_note", "Small Text", "Why", read_only=1),
	], perms=READONLY_AUDIT,
	   autoname="PTX-.YYYY.-.######", naming_rule="Expression (old style)", sort_field="creation", in_create=True,
	   extra={"modified": "2026-10-02 00:00:00.000000"}),   # the indexes, expires_at, reconciliation, captured_at,
	                                                        # checkout_started_at came later

	dt("TEX Payment Allocation", PM, [
		F("property", "Link", "Hotel", "Property"),
		F("transaction", "Link", "Transaction", "TEX Payment Transaction", in_list_view=1, search_index=1),
		F("allocation_type", "Select", "Type", ["Allocate", "Transfer", "Refund", "Release"], in_list_view=1),
		F("amount", "Currency", "Amount", options="currency", in_list_view=1),
		F("currency", "Link", "Currency", "Currency"),
		CB(),
		F("booking", "Link", "Booking", "TEX Booking", in_list_view=1, search_index=1),
		F("reservation", "Link", "Reservation", "Reservation"),
		F("payment_link", "Link", "Payment link", "TEX Payment Link"),
		F("reason", "Small Text", "Reason"),
		F("actor", "Link", "Actor", "User"),
		F("idempotency_key", "Data", "Idempotency key", unique=1, read_only=1),
	], perms=READONLY_AUDIT,
	   autoname="PAL-.YYYY.-.######", naming_rule="Expression (old style)", sort_field="creation", in_create=True,
	   extra={"modified": "2026-09-29 00:00:00.000000"}),         # indexed for the locking reads (re-review 4)
]

# ═══ TEX CRM ══════════════════════════════════════════════════════════════
R = "TEX CRM"
CRM_SPECS = [
	dt("TEX Guest Segment", R, [
		F("segment_name", "Data", "Segment", reqd=1, in_list_view=1,
		  description="Unique within its enterprise"),
		F("system_key", "Data", "System key", read_only=1, description="Preset shared by every tenant (read-only)"),
		F("description", "Small Text", "Description"),
		F("is_dynamic", "Check", "Dynamic", default="1"),
		CB(),
		F("enterprise", "Link", "Enterprise", "TEX Enterprise", in_standard_filter=1,
		  description="The tenant that owns this segment; empty for presets"),
		F("member_count", "Int", "Members", read_only=1, in_list_view=1),
		F("last_evaluated", "Datetime", "Last evaluated", read_only=1),
		SB("Rules"),
		F("rules_json", "Code", "Rules", "JSON"),
	], perms=CRM, autoname="hash", naming_rule="Random"),

	dt("TEX Communication", R, [
		F("guest", "Link", "Guest", "Guest", in_list_view=1, in_standard_filter=1),
		F("property", "Link", "Property", "Property"),
		F("booking", "Link", "Booking", "TEX Booking"),
		F("reservation", "Link", "Reservation", "Reservation"),
		F("channel", "Select", "Channel", ["Email", "SMS", "WhatsApp", "Phone", "Note"], in_list_view=1),
		F("direction", "Select", "Direction", ["Outbound", "Inbound", "Internal"], default="Outbound"),
		CB(),
		F("status", "Select", "Status", ["Queued", "Sent", "Delivered", "Failed", "Logged"], default="Logged",
		  in_list_view=1),
		F("consent_basis", "Select", "Basis", ["Transactional", "Marketing", "Legitimate Interest"],
		  default="Transactional"),
		F("template", "Data", "Template"),
		F("sent_at", "Datetime", "Sent at"),
		F("actor", "Link", "Actor", "User"),
		F("email_queue", "Data", "E-mail queue entry", read_only=1,
		  description="The Email Queue row of this message; its status is synced every 5 minutes (ADR-047)."),
		F("delivery_error", "Data", "Delivery error", read_only=1),
		SB("Message"),
		F("subject", "Data", "Subject", in_list_view=1),
		F("body", "Text", "Body"),
	], perms=CRM, autoname="COM-.YYYY.-.######", naming_rule="Expression (old style)", sort_field="creation"),

	dt("TEX Abandoned Booking", R, [
		F("property", "Link", "Hotel", "Property", in_standard_filter=1),
		F("site", "Link", "Site", "TEX Booking Site"),
		F("session_id", "Data", "Session", permlevel=1),              # withheld: leads to the person (ADR-056)
		F("stage_reached", "Select", "Stage", ["search", "room_view", "quote", "guest_details",
		                                       "payment_started"], in_list_view=1),
		F("status", "Select", "Status", ["Open", "Contacted", "Recovered", "Dismissed"], default="Open",
		  in_list_view=1, in_standard_filter=1),
		CB(),
		# contact data: kept only with the profile's consent, withheld from Desk / REST (ADR-056 review)
		F("guest", "Link", "Guest", "Guest", permlevel=1),
		F("email", "Data", "Email", options="Email", permlevel=1),
		F("phone", "Data", "Phone", permlevel=1),
		F("consent_marketing", "Check", "Marketing consent"),
		F("value", "Currency", "Value", options="currency", in_list_view=1),
		F("currency", "Link", "Currency", "Currency"),
		F("check_in", "Date", "Check-in"),
		F("check_out", "Date", "Check-out"),
		F("quote", "Link", "Quote", "TEX Quote", permlevel=1),
		F("last_event_at", "Datetime", "Last activity"),
		F("recovered_booking", "Link", "Recovered booking", "TEX Booking", permlevel=1),
	], perms=[*CRM, INTERNALS_RW], autoname="ABN-.YYYY.-.#####", naming_rule="Expression (old style)"),

	dt("TEX Loyalty Tier", R, [
		F("tier_name", "Data", "Tier", reqd=1, in_list_view=1),
		F("min_points", "Int", "From points", in_list_view=1),
		F("earn_multiplier", "Float", "Earn ×", default="1", in_list_view=1, **V),
	], istable=True),

	dt("TEX Loyalty Blackout", R, [
		F("date_from", "Date", "From", reqd=1, in_list_view=1),
		F("date_to", "Date", "To", reqd=1, in_list_view=1),
		F("note", "Data", "Note", in_list_view=1),
		F("applies_to", "Select", "Applies to", ["Redemption", "Earning", "Both"], default="Redemption",
		  in_list_view=1, description="Redemption: points cannot pay for stays on these dates. "
		                              "Earning: stays arriving on these dates earn nothing."),
	], istable=True),

	dt("TEX Loyalty Earn Rule", R, [
		F("basis", "Select", "Basis", ["MONEY", "NIGHTS", "STAY", "EXTRA", "ROOM"], reqd=1, in_list_view=1),
		F("rate", "Float", "Points per unit", in_list_view=1, **V),
		F("room_type", "Link", "Room type", "Room Type"),
		F("extra", "Link", "Extra", "TEX Extra"),
		F("date_from", "Date", "Stay from"),
		F("date_to", "Date", "Stay to"),
	], istable=True),

	dt("TEX Loyalty Program", R, [
		F("program_name", "Data", "Program", reqd=1, in_list_view=1,
		  description="Unique for its hotel or hotel group"),
		F("property", "Link", "Hotel", "Property"),
		F("hotel_group", "Link", "Hotel group", "TEX Hotel Group"),
		F("enabled", "Check", "Enabled", default="1", in_list_view=1),
		CB(),
		F("currency", "Link", "Currency", "Currency"),
		F("point_value", "Currency", "Value of 1 point (burn)", options="currency", **V),
		F("min_redeem_points", "Int", "Min points to redeem"),
		F("max_redeem_percent", "Percent", "Max % of stay payable with points", default="100", **V,
		  description="0 = points cannot be redeemed"),
		F("pending_days", "Int", "Points available N days after checkout", default="1"),
		F("expiry_months", "Int", "Points expire after (months)", default="24"),
		SB("Earning"),
		F("earn_rules", "Table", "Earn rules", "TEX Loyalty Earn Rule"),
		F("tiers", "Table", "Tiers", "TEX Loyalty Tier"),
		SB("Blackouts"),
		F("blackouts", "Table", "Blackout dates", "TEX Loyalty Blackout"),
	], perms=CRM, autoname="hash", naming_rule="Random"),

	dt("TEX Loyalty Ledger", R, [
		F("program", "Link", "Program", "TEX Loyalty Program", reqd=1),
		F("guest", "Link", "Guest", "Guest", reqd=1, in_list_view=1, in_standard_filter=1),
		F("entry_type", "Select", "Entry", ["Earn", "Burn", "Adjust", "Expire", "Reverse"], in_list_view=1),
		F("points", "Int", "Points", in_list_view=1),
		F("status", "Select", "Status", ["Pending", "Available", "Used", "Expired", "Reversed"], in_list_view=1),
		CB(),
		F("available_on", "Date", "Available on"),
		F("expires_on", "Date", "Expires on"),
		F("booking", "Link", "Booking", "TEX Booking"),
		F("reservation", "Link", "Reservation", "Reservation"),
		F("property", "Link", "Hotel", "Property", in_standard_filter=1,
		  description="The hotel the entry belongs to: its stay's or booking's, or the hotel a manual "
		              "adjustment was made for (ADR-056)"),
		F("reason", "Small Text", "Reason"),
		F("actor", "Link", "Actor", "User"),
		F("stay_fingerprint", "Data", "Stay fingerprint", read_only=1,
		  description="What the earning was computed from; a rule change never rewrites it (G-24)"),
		F("explanation", "Code", "How the points were earned", "JSON", read_only=1),
	], perms=READONLY_AUDIT,
	   autoname="LYL-.######", naming_rule="Expression (old style)", sort_field="creation", in_create=True),
]

# ═══ TEX Connect ══════════════════════════════════════════════════════════
X = "TEX Connect"
CONNECT_SPECS = [
	dt("TEX Integration Connection", X, [
		F("label", "Data", "Label", reqd=1, in_list_view=1),
		F("property", "Link", "Hotel", "Property", in_standard_filter=1),
		F("category", "Select", "Category", ["PMS", "Channel Manager", "Payments", "FX", "Email", "SMS",
		                                     "WhatsApp"], reqd=1, in_list_view=1),
		F("adapter", "Data", "Adapter", reqd=1, in_list_view=1),
		F("enabled", "Check", "Enabled", default="1", in_list_view=1),
		F("environment", "Select", "Environment", ["Sandbox", "Production"], default="Sandbox"),
		CB(),
		F("endpoint_url", "Data", "Endpoint"),
		F("api_key", "Password", "API key", description="Stored encrypted; never shown again"),
		F("secret", "Password", "Secret"),
		F("settings_json", "Code", "Settings", "JSON"),
		SB("Status"),
		F("last_sync_at", "Datetime", "Last sync", read_only=1),
		F("last_status", "Data", "Last status", read_only=1),
		F("last_error", "Small Text", "Last error", read_only=1),
	], perms=[SM, HA_RO], autoname="CON-.####", naming_rule="Expression (old style)", title_field="label"),

	dt("TEX Integration Outbox", X, [
		F("connection", "Link", "Connection", "TEX Integration Connection", in_list_view=1),
		F("property", "Link", "Hotel", "Property", in_standard_filter=1),
		F("kind", "Select", "Kind", ["Reservation", "ARI"], default="Reservation", in_list_view=1,
		  in_standard_filter=1),
		F("event", "Data", "Event", in_list_view=1),
		F("status", "Select", "Status", ["Pending", "Sent", "Failed", "Dead"], default="Pending", in_list_view=1,
		  in_standard_filter=1),
		F("attempts", "Int", "Attempts"),
		F("next_attempt_at", "Datetime", "Next attempt"),
		F("claimed_until", "Datetime", "Claimed until", read_only=1),
		F("claim_token", "Data", "Claim", read_only=1),
		CB(),
		F("reference_doctype", "Link", "Reference type", "DocType"),
		F("reference_name", "Dynamic Link", "Reference", "reference_doctype"),
		F("idempotency_key", "Data", "Idempotency key", unique=1),
		F("sent_at", "Datetime", "Sent at"),
		F("last_error", "Small Text", "Last error"),
		SB("Payload"),
		F("payload", "Code", "Payload", "JSON"),
	], perms=[perm("System Manager", "full"), perm("Hotel Admin", "readonly")], autoname="hash",
	   track_changes=False, sort_field="creation"),

	# ─── distribution (G-69, ADR-039) ─────────────────────────────────────
	dt("TEX Channel Mapping", X, [
		F("connection", "Link", "Connection", "TEX Integration Connection", reqd=1, in_list_view=1,
		  in_standard_filter=1),
		F("property", "Link", "Hotel", "Property", read_only=1, in_standard_filter=1),
		F("enabled", "Check", "Enabled", default="1", in_list_view=1),
		F("room_type", "Link", "Room type", "Room Type", reqd=1, in_list_view=1),
		F("external_room_code", "Data", "Channel room code", reqd=1, in_list_view=1),
		F("external_rate_code", "Data", "Channel rate code", reqd=1, in_list_view=1),
		CB(),
		F("board", "Data", "Board", reqd=1, description="TEX board code sold under this rate"),
		F("rate_plan", "Link", "Rate plan", "Rate Plan"),
		F("market", "Link", "Market", "TEX Market", reqd=1),
		F("sales_channel", "Link", "Sales channel", "TEX Sales Channel", reqd=1),
		F("contract", "Link", "Contract", "TEX Contract",
		  description="Empty: the contract TEX would sell this market and channel with"),
		F("sell_currency", "Link", "Currency", "Currency", reqd=1),
		F("occupancies", "Data", "Adults priced", default="2", description="Comma-separated, e.g. 1,2,3"),
		F("horizon_days", "Int", "Days ahead", default="90"),
	], perms=[SM, HA_RO], autoname="hash", title_field="external_room_code"),

	dt("TEX Channel ARI Day", X, [
		F("connection", "Link", "Connection", "TEX Integration Connection", reqd=1, in_standard_filter=1),
		F("mapping", "Link", "Mapping", "TEX Channel Mapping", reqd=1, in_standard_filter=1),
		F("property", "Link", "Hotel", "Property", in_standard_filter=1),
		F("ari_date", "Date", "Date", reqd=1, in_list_view=1),
		F("fingerprint", "Data", "Fingerprint", read_only=1),
		F("pushed_at", "Datetime", "Accepted at", read_only=1, in_list_view=1),
		F("payload", "Code", "Values", "JSON", read_only=1),
	], perms=[perm("System Manager", "full"), perm("Hotel Admin", "readonly")], track_changes=False,
	   sort_field="ari_date"),

	dt("TEX Channel Inbound", X, [
		F("connection", "Link", "Connection", "TEX Integration Connection", reqd=1, in_list_view=1,
		  in_standard_filter=1),
		F("property", "Link", "Hotel", "Property", in_standard_filter=1),
		F("provider_ref", "Data", "Channel booking id", in_list_view=1, in_standard_filter=1),
		F("event", "Select", "Event", ["new", "modified", "cancelled"], in_list_view=1),
		F("status", "Select", "Status", ["Received", "Applied", "Failed", "Dead", "Ignored"], default="Received",
		  in_list_view=1, in_standard_filter=1),
		F("attempts", "Int", "Attempts"),
		F("next_attempt_at", "Datetime", "Next attempt"),
		CB(),
		F("received_at", "Datetime", "Received at", in_list_view=1),
		F("applied_at", "Datetime", "Applied at"),
		F("booking", "Link", "Booking", "TEX Booking"),
		F("idempotency_key", "Data", "Idempotency key", unique=1),
		F("warning", "Small Text", "Warning", description="e.g. accepted although TEX showed no room left"),
		F("last_error", "Small Text", "Last error"),
		SB("Payload"),
		F("payload", "Code", "Reservation (normalised)", "JSON"),
	], perms=[perm("System Manager", "full"), perm("Hotel Admin", "readonly")], autoname="hash",
	   track_changes=False, sort_field="creation"),
]

SPECS = PLATFORM_SPECS + COMMERCIAL_SPECS + BOOKING_SPECS + PAYMENT_SPECS + CRM_SPECS + CONNECT_SPECS
_unused = (TAB,)
