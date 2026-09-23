// Declarative editors for the selling-policy DocTypes served by kamra/tex/api/policies.py.
// Field names follow kamra/tex/devtools/doctype_specs.py; labels/help are i18n keys.
import type { FieldKind } from "../lib/util"
import {
  APPLIES_TO,
  BOARDS,
  CHILD_PRICING,
  COMBINE,
  DEPOSIT,
  EXTRA_CATEGORIES,
  EXTRA_MODES,
  TAX_APPLIES,
  TAX_KINDS,
  FX_MODES,
  FX_PROVIDERS,
  INFANT_PRICING,
  OCC_TARGETS,
  OPS_MARKUP,
  OPS_OCC,
  PENALTY,
  PROMO_KINDS,
  PROMO_STAGE,
  PROMO_VALUE,
  RATE_TYPES,
  STAY_MATCH,
  TAX_CATEGORIES,
  TRIGGERS,
} from "../lib/options"

export type Source = "market" | "channel" | "currency" | "room_type" | "contract" | "rate_plan" | "board"
export type Doc = Record<string, unknown>

export interface PolicyField {
  key: string
  kind: FieldKind | "textarea" | "link" | "table" | "property"
  label: string
  help?: string
  /** help key that depends on the current value, e.g. "rates.fx_mode_help.{value}" */
  helpByValue?: string
  required?: boolean
  /** enum values; labels are rates.<group>.<value> */
  options?: readonly string[]
  group?: string
  source?: Source
  /** i18n key of the "blank" choice for optional selects / links */
  blank?: string
  decimals?: number
  allowNegative?: boolean
  showIf?: (d: Doc) => boolean
  suffix?: (d: Doc) => string | null
  readOnly?: boolean
  wide?: boolean
  /** table fields: child columns */
  columns?: TableColumn[]
}

export interface TableColumn {
  key: string
  kind: FieldKind
  label: string
  help?: string
  options?: readonly string[]
  group?: string
  source?: Source | "band"
  blank?: string
  decimals?: number
  allowNegative?: boolean
  required?: boolean
  percentWhenOp?: boolean
  default?: string | number
}

export interface PolicySection {
  title: string
  help?: string
  fields: PolicyField[]
}

export interface ListCol {
  key: string
  label: string
  render: "text" | "code" | "enum" | "op" | "status" | "rev" | "datetime" | "date" | "check" | "pair" | "decimal" | "room" | "contract"
  group?: string
  hideBelow?: "sm" | "md" | "lg"
}

export interface PolicyKind {
  slug: string
  doctype: string
  cap: string
  revisioned: boolean
  navLabel: string
  title: string
  singular: string
  intro: string
  titleField: string | ((d: Doc) => string)
  propertyRequired: boolean
  sections: PolicySection[]
  list: ListCol[]
  newDoc: () => Doc
}

const pct = (op: unknown) => op === "ADJUST_PERCENT" || op === "PERCENT_OF" || op === "PERCENT"

export const POLICY_KINDS: PolicyKind[] = [
  // ─── Markup ────────────────────────────────────────────────────────────
  {
    slug: "markup",
    doctype: "TEX Markup Rule",
    cap: "markup.edit",
    revisioned: true,
    navLabel: "rates.nav.markup",
    title: "rates.policy.markup.title",
    singular: "rates.policy.markup.one",
    intro: "rates.policy.markup.intro",
    titleField: (d) => String(d.label || d.name || ""),
    propertyRequired: false,
    newDoc: () => ({ op: "ADJUST_PERCENT", value: "", combine: "REPLACE", priority: 0 }),
    list: [
      { key: "label", label: "rates.f.label", render: "text" },
      { key: "op", label: "rates.f.markup", render: "op" },
      { key: "tex_status", label: "rates.f.status", render: "status" },
      { key: "revision_no", label: "rates.f.revision", render: "rev", hideBelow: "sm" },
      { key: "active_from", label: "rates.f.active_from", render: "datetime", hideBelow: "md" },
    ],
    sections: [
      {
        title: "rates.policy.section.rule",
        fields: [
          { key: "label", kind: "text", label: "rates.f.label", help: "rates.h.markup_label" },
          { key: "op", kind: "select", label: "rates.f.markup_op", required: true, options: OPS_MARKUP, group: "op", helpByValue: "rates.markup_help" },
          {
            key: "value",
            kind: "decimal",
            label: "rates.f.value",
            required: true,
            allowNegative: true,
            suffix: (d) => (pct(d.op) ? "%" : d.op === "MULTIPLY" ? "×" : String(d.currency || "")),
          },
          { key: "currency", kind: "link", source: "currency", label: "rates.f.currency_fixed", help: "rates.h.currency_fixed", showIf: (d) => d.op === "ADD", blank: "rates.common.contract_currency" },
          { key: "combine", kind: "select", label: "rates.f.combine", options: COMBINE, group: "combine", helpByValue: "rates.combine_help" },
          { key: "priority", kind: "int", label: "rates.f.priority", help: "rates.h.markup_priority" },
        ],
      },
      {
        title: "rates.policy.section.scope",
        help: "rates.policy.markup.scope_help",
        fields: [
          { key: "property", kind: "property", label: "rates.f.hotel" },
          { key: "market", kind: "link", source: "market", label: "rates.f.market", blank: "rates.common.any_market" },
          { key: "contract", kind: "link", source: "contract", label: "rates.f.contract", blank: "rates.common.any_contract" },
          { key: "room_type", kind: "link", source: "room_type", label: "rates.f.room_type", blank: "rates.common.all_rooms" },
          { key: "sales_channel", kind: "link", source: "channel", label: "rates.f.channel", blank: "rates.common.all_channels" },
          { key: "stay_from", kind: "date", label: "rates.f.stay_from" },
          { key: "stay_to", kind: "date", label: "rates.f.stay_to" },
        ],
      },
    ],
  },
  // ─── Promotions & coupons ───────────────────────────────────────────────
  {
    slug: "promotions",
    doctype: "TEX Promotion",
    cap: "promotion.edit",
    revisioned: true,
    navLabel: "rates.nav.promotions",
    title: "rates.policy.promotions.title",
    singular: "rates.policy.promotions.one",
    intro: "rates.policy.promotions.intro",
    titleField: "promotion_name",
    propertyRequired: false,
    newDoc: () => ({ kind: "SPECIAL_OFFER", trigger: "Automatic", value_type: "PERCENT", value: "", stage: "SELL", applies_to: "ACCOMMODATION", stay_match: "ANY_NIGHT", stackable: 1, exclusive: 0, priority: 0 }),
    list: [
      { key: "promotion_name", label: "rates.f.promotion_name", render: "text" },
      { key: "kind", label: "rates.f.kind", render: "enum", group: "promo_kind", hideBelow: "sm" },
      { key: "code", label: "rates.f.code", render: "code" },
      { key: "tex_status", label: "rates.f.status", render: "status" },
      { key: "revision_no", label: "rates.f.revision", render: "rev", hideBelow: "md" },
      { key: "active_from", label: "rates.f.active_from", render: "datetime", hideBelow: "lg" },
    ],
    sections: [
      {
        title: "rates.policy.section.offer",
        fields: [
          { key: "promotion_name", kind: "text", label: "rates.f.promotion_name", required: true },
          { key: "kind", kind: "select", label: "rates.f.kind", options: PROMO_KINDS, group: "promo_kind" },
          { key: "trigger", kind: "select", label: "rates.f.trigger", options: TRIGGERS, group: "trigger", helpByValue: "rates.trigger_help" },
          { key: "code", kind: "text", label: "rates.f.coupon_code", help: "rates.h.coupon_code", showIf: (d) => d.trigger === "Code", required: true },
          { key: "value_type", kind: "select", label: "rates.f.value_type", options: PROMO_VALUE, group: "promo_value", helpByValue: "rates.promo_value_help" },
          {
            key: "value",
            kind: "decimal",
            label: "rates.f.value",
            showIf: (d) => d.value_type !== "FREE_NIGHTS" && d.value_type !== "VALUE_ADDED",
            suffix: (d) => (d.value_type === "PERCENT" ? "%" : d.value_type === "MULTIPLIER" ? "×" : String(d.currency || "")),
          },
          { key: "currency", kind: "link", source: "currency", label: "rates.f.currency_fixed", showIf: (d) => d.value_type === "FIXED_STAY" || d.value_type === "FIXED_NIGHT", blank: "rates.common.sell_currency" },
          { key: "free_nights_stay", kind: "int", label: "rates.f.free_nights_stay", help: "rates.h.free_nights", showIf: (d) => d.value_type === "FREE_NIGHTS" },
          { key: "free_nights_pay", kind: "int", label: "rates.f.free_nights_pay", showIf: (d) => d.value_type === "FREE_NIGHTS" },
          { key: "value_added", kind: "text", label: "rates.f.value_added", help: "rates.h.value_added", showIf: (d) => d.value_type === "VALUE_ADDED" },
          { key: "stage", kind: "select", label: "rates.f.stage", options: PROMO_STAGE, group: "stage", helpByValue: "rates.stage_help" },
          { key: "applies_to", kind: "select", label: "rates.f.applies_to", options: APPLIES_TO, group: "applies_to" },
          { key: "property", kind: "property", label: "rates.f.hotel" },
        ],
      },
      {
        title: "rates.policy.section.dates",
        help: "rates.h.sale_vs_stay",
        fields: [
          { key: "sale_from", kind: "date", label: "rates.f.sale_from" },
          { key: "sale_to", kind: "date", label: "rates.f.sale_to" },
          { key: "min_lead_days", kind: "int", label: "rates.f.min_lead_days", help: "rates.h.min_lead_days" },
          { key: "max_lead_days", kind: "int", label: "rates.f.max_lead_days", help: "rates.h.max_lead_days" },
          { key: "stay_from", kind: "date", label: "rates.f.stay_from" },
          { key: "stay_to", kind: "date", label: "rates.f.stay_to" },
          { key: "stay_match", kind: "select", label: "rates.f.stay_match", options: STAY_MATCH, group: "stay_match", helpByValue: "rates.stay_match_help" },
          { key: "min_nights", kind: "int", label: "rates.f.min_nights", help: "rates.h.zero_no_limit" },
          { key: "max_nights", kind: "int", label: "rates.f.max_nights", help: "rates.h.zero_no_limit" },
        ],
      },
      {
        title: "rates.policy.section.eligibility",
        help: "rates.policy.promotions.eligibility_help",
        fields: [
          { key: "markets", kind: "csv", source: "market", label: "rates.f.markets", blank: "rates.common.all_markets" },
          { key: "channels", kind: "csv", source: "channel", label: "rates.f.channels", blank: "rates.common.all_channels" },
          { key: "room_types", kind: "csv", source: "room_type", label: "rates.f.room_types", blank: "rates.common.all_rooms" },
          { key: "boards", kind: "csv", source: "board", label: "rates.f.boards", blank: "rates.common.all_boards" },
          { key: "rate_plans", kind: "csv", source: "rate_plan", label: "rates.f.rate_plans", blank: "rates.common.all_rate_plans" },
          { key: "contracts", kind: "csv", source: "contract", label: "rates.f.contracts", blank: "rates.common.all_contracts" },
          { key: "requires_extras", kind: "text", label: "rates.f.requires_extras", help: "rates.h.requires_extras" },
          { key: "min_basket", kind: "decimal", label: "rates.f.min_basket", help: "rates.h.min_basket" },
          { key: "member_only", kind: "check", label: "rates.f.member_only", help: "rates.h.member_only" },
        ],
      },
      {
        title: "rates.policy.section.combination",
        help: "rates.h.stacking_rules",
        fields: [
          { key: "stackable", kind: "check", label: "rates.f.stackable", help: "rates.h.stackable" },
          { key: "exclusive", kind: "check", label: "rates.f.exclusive", help: "rates.h.exclusive" },
          { key: "priority", kind: "int", label: "rates.f.priority", help: "rates.h.promo_priority" },
          { key: "promo_group", kind: "text", label: "rates.f.offer_group", help: "rates.h.promo_group" },
          { key: "usage_limit", kind: "int", label: "rates.f.usage_limit", help: "rates.h.usage_limit" },
          { key: "per_guest_limit", kind: "int", label: "rates.f.per_guest_limit", help: "rates.h.per_guest_limit" },
          { key: "times_redeemed", kind: "int", label: "rates.f.times_redeemed", readOnly: true },
        ],
      },
    ],
  },
  // ─── FX policies ─────────────────────────────────────────────────────────
  {
    slug: "fx-policies",
    doctype: "TEX FX Policy",
    cap: "fx.edit",
    revisioned: true,
    navLabel: "rates.nav.fx",
    title: "rates.policy.fx.title",
    singular: "rates.policy.fx.one",
    intro: "rates.policy.fx.intro",
    titleField: (d) => (d.from_currency && d.to_currency ? `${d.from_currency} → ${d.to_currency}` : String(d.name || "")),
    propertyRequired: false,
    newDoc: () => ({ mode: "PROVIDER_PERCENT", provider: "TCMB", rate_type: "FOREX_SELLING", adjustment: "", max_age_days: 4 }),
    list: [
      { key: "from_currency", label: "rates.f.pair", render: "pair" },
      { key: "mode", label: "rates.f.fx_mode", render: "enum", group: "fx_mode" },
      { key: "tex_status", label: "rates.f.status", render: "status" },
      { key: "revision_no", label: "rates.f.revision", render: "rev", hideBelow: "sm" },
      { key: "active_from", label: "rates.f.active_from", render: "datetime", hideBelow: "md" },
    ],
    sections: [
      {
        title: "rates.policy.section.conversion",
        help: "rates.policy.fx.conversion_help",
        fields: [
          { key: "from_currency", kind: "link", source: "currency", label: "rates.f.from_currency", required: true },
          { key: "to_currency", kind: "link", source: "currency", label: "rates.f.to_currency", required: true },
          { key: "mode", kind: "select", label: "rates.f.fx_mode", required: true, options: FX_MODES, group: "fx_mode", helpByValue: "rates.fx_mode_help" },
          { key: "provider", kind: "select", label: "rates.f.provider", options: FX_PROVIDERS, group: "fx_provider", showIf: (d) => d.mode !== "MANUAL" },
          { key: "rate_type", kind: "select", label: "rates.f.rate_type", options: RATE_TYPES, group: "rate_type", showIf: (d) => d.mode !== "MANUAL" },
          { key: "manual_rate", kind: "decimal", decimals: 9, label: "rates.f.manual_rate", help: "rates.h.manual_rate", showIf: (d) => d.mode === "MANUAL", required: true },
          {
            key: "adjustment",
            kind: "decimal",
            allowNegative: true,
            label: "rates.f.fx_adjustment",
            help: "rates.h.fx_adjustment",
            showIf: (d) => d.mode === "PROVIDER_PERCENT" || d.mode === "PROVIDER_FIXED",
            suffix: (d) => (d.mode === "PROVIDER_PERCENT" ? "%" : String(d.to_currency || "")),
          },
          { key: "max_age_days", kind: "int", label: "rates.f.max_age_days", help: "rates.h.max_age_days", showIf: (d) => d.mode !== "MANUAL" },
          { key: "property", kind: "property", label: "rates.f.hotel", blank: "rates.common.global_default" },
        ],
      },
    ],
  },
  // ─── Pricing policies (inherited age bands / occupancy defaults) ────────
  {
    slug: "pricing-policies",
    doctype: "TEX Pricing Policy",
    cap: "contract.edit",
    revisioned: true,
    navLabel: "rates.nav.pricing",
    title: "rates.policy.pricing.title",
    singular: "rates.policy.pricing.one",
    intro: "rates.policy.pricing.intro",
    titleField: "policy_name",
    propertyRequired: false,
    newDoc: () => ({ age_bands: [], occupancy_rules: [] }),
    list: [
      { key: "policy_name", label: "rates.f.policy_name", render: "text" },
      { key: "tex_status", label: "rates.f.status", render: "status" },
      { key: "revision_no", label: "rates.f.revision", render: "rev", hideBelow: "sm" },
      { key: "active_from", label: "rates.f.active_from", render: "datetime", hideBelow: "md" },
    ],
    sections: [
      {
        title: "rates.policy.section.scope",
        help: "rates.policy.pricing.scope_help",
        fields: [
          { key: "policy_name", kind: "text", label: "rates.f.policy_name", required: true },
          { key: "property", kind: "property", label: "rates.f.hotel", blank: "rates.common.all_hotels" },
          { key: "market", kind: "link", source: "market", label: "rates.f.market", blank: "rates.common.any_market" },
        ],
      },
      {
        title: "rates.tab.ages",
        help: "rates.ages.intro",
        fields: [
          {
            key: "age_bands",
            kind: "table",
            label: "rates.tab.ages",
            columns: [
              { key: "band_code", kind: "text", label: "rates.f.band_code", required: true },
              { key: "label", kind: "text", label: "rates.f.band_label" },
              { key: "from_age", kind: "decimal", decimals: 2, label: "rates.f.from_age", help: "rates.h.from_age" },
              { key: "to_age", kind: "decimal", decimals: 2, label: "rates.f.to_age", help: "rates.h.to_age" },
              { key: "is_infant", kind: "check", label: "rates.f.is_infant" },
            ],
          },
        ],
      },
      {
        title: "rates.tab.occupancy",
        help: "rates.policy.pricing.occ_help",
        fields: [
          {
            key: "occupancy_rules",
            kind: "table",
            label: "rates.tab.occupancy",
            columns: [
              { key: "target", kind: "select", label: "rates.f.target", options: OCC_TARGETS, group: "target", required: true, default: "CHILD" },
              { key: "position", kind: "int", label: "rates.f.position", help: "rates.h.position" },
              { key: "age_band", kind: "select", source: "band", label: "rates.f.age_band", blank: "rates.common.any" },
              { key: "combination", kind: "text", label: "rates.f.combination", help: "rates.h.combination" },
              { key: "room_type", kind: "select", source: "room_type", label: "rates.f.room_type", blank: "rates.common.all_rooms" },
              { key: "op", kind: "select", label: "rates.f.rule", options: OPS_OCC, group: "op", required: true, default: "PERCENT_OF" },
              { key: "value", kind: "decimal", label: "rates.f.value", allowNegative: true, percentWhenOp: true },
              { key: "is_override", kind: "check", label: "rates.f.is_override", help: "rates.policy.pricing.override_help" },
              { key: "note", kind: "text", label: "rates.f.note" },
            ],
          },
        ],
      },
    ],
  },
  // ─── Cancellation policies ───────────────────────────────────────────────
  {
    slug: "cancellation",
    doctype: "TEX Cancellation Policy",
    cap: "contract.edit",
    revisioned: false,
    navLabel: "rates.nav.cancellation",
    title: "rates.policy.cancellation.title",
    singular: "rates.policy.cancellation.one",
    intro: "rates.policy.cancellation.intro",
    titleField: "policy_name",
    propertyRequired: false,
    newDoc: () => ({ refundable: 1, no_show_type: "NIGHTS", no_show_value: "1", rules: [] }),
    list: [
      { key: "policy_name", label: "rates.f.policy_name", render: "text" },
      { key: "refundable", label: "rates.f.refundable", render: "check" },
      { key: "modified", label: "rates.f.modified", render: "datetime", hideBelow: "md" },
    ],
    sections: [
      {
        title: "rates.policy.section.policy",
        fields: [
          { key: "policy_name", kind: "text", label: "rates.f.policy_name", required: true },
          { key: "property", kind: "property", label: "rates.f.hotel" },
          { key: "refundable", kind: "check", label: "rates.f.refundable", help: "rates.h.refundable" },
          { key: "no_show_type", kind: "select", label: "rates.f.no_show_type", options: PENALTY, group: "penalty" },
          { key: "no_show_value", kind: "decimal", label: "rates.f.no_show_value", suffix: (d) => (d.no_show_type === "PERCENT" ? "%" : d.no_show_type === "NIGHTS" ? "N" : null) },
          { key: "description", kind: "textarea", label: "rates.f.guest_text", help: "rates.h.guest_text", wide: true },
        ],
      },
      {
        title: "rates.policy.section.penalties",
        help: "rates.policy.cancellation.rules_help",
        fields: [
          {
            key: "rules",
            kind: "table",
            label: "rates.policy.section.penalties",
            columns: [
              { key: "days_before_arrival", kind: "int", label: "rates.f.days_before_arrival", help: "rates.h.days_before_arrival" },
              { key: "penalty_type", kind: "select", label: "rates.f.penalty_type", options: PENALTY, group: "penalty", required: true, default: "PERCENT" },
              { key: "penalty_value", kind: "decimal", label: "rates.f.value" },
            ],
          },
        ],
      },
    ],
  },
  // ─── Payment policies ─────────────────────────────────────────────────────
  {
    slug: "payment",
    doctype: "TEX Payment Policy",
    cap: "contract.edit",
    revisioned: false,
    navLabel: "rates.nav.payment",
    title: "rates.policy.payment.title",
    singular: "rates.policy.payment.one",
    intro: "rates.policy.payment.intro",
    titleField: "policy_name",
    propertyRequired: false,
    newDoc: () => ({ deposit_type: "PERCENT", deposit_value: "30", balance_due_days: 14, allow_pay_at_hotel: 0 }),
    list: [
      { key: "policy_name", label: "rates.f.policy_name", render: "text" },
      { key: "deposit_type", label: "rates.f.deposit_type", render: "enum", group: "deposit" },
      { key: "modified", label: "rates.f.modified", render: "datetime", hideBelow: "md" },
    ],
    sections: [
      {
        title: "rates.policy.section.policy",
        fields: [
          { key: "policy_name", kind: "text", label: "rates.f.policy_name", required: true },
          { key: "property", kind: "property", label: "rates.f.hotel" },
          { key: "deposit_type", kind: "select", label: "rates.f.deposit_type", options: DEPOSIT, group: "deposit", helpByValue: "rates.deposit_help" },
          {
            key: "deposit_value",
            kind: "decimal",
            label: "rates.f.value",
            showIf: (d) => d.deposit_type === "PERCENT" || d.deposit_type === "NIGHTS" || d.deposit_type === "FIXED",
            suffix: (d) => (d.deposit_type === "PERCENT" ? "%" : d.deposit_type === "NIGHTS" ? "N" : null),
          },
          { key: "balance_due_days", kind: "int", label: "rates.f.balance_due_days", help: "rates.h.balance_due_days" },
          { key: "allow_pay_at_hotel", kind: "check", label: "rates.f.allow_pay_at_hotel", help: "rates.h.allow_pay_at_hotel" },
          { key: "description", kind: "textarea", label: "rates.f.guest_text", help: "rates.h.guest_text", wide: true },
        ],
      },
    ],
  },
  // ─── Extras ─────────────────────────────────────────────────────────────
  {
    slug: "extras",
    doctype: "TEX Extra",
    cap: "contract.edit",
    // a price change is a new revision from its activation; sold stays keep theirs (G-20)
    revisioned: true,
    navLabel: "rates.nav.extras",
    title: "rates.policy.extras.title",
    singular: "rates.policy.extras.one",
    intro: "rates.policy.extras.intro",
    titleField: (d) => String(d.extra_name || d.extra_code || d.name || ""),
    propertyRequired: true,
    newDoc: () => ({ category: "Service", pricing_mode: "UNIT", amount: "", child_pricing: "SAME_AS_ADULT", infant_pricing: "FREE", tax_category: "SERVICE", bookable_online: 1, bookable_after_booking: 1, price_rules: [] }),
    list: [
      { key: "extra_code", label: "rates.f.extra_code", render: "code" },
      { key: "extra_name", label: "rates.f.extra_name", render: "text" },
      { key: "category", label: "rates.f.category", render: "enum", group: "extra_category", hideBelow: "md" },
      { key: "pricing_mode", label: "rates.f.pricing_mode", render: "enum", group: "extra_mode", hideBelow: "sm" },
      { key: "amount", label: "rates.f.price", render: "decimal" },
      { key: "tex_status", label: "rates.f.status", render: "status" },
      { key: "revision_no", label: "rates.f.revision", render: "rev", hideBelow: "sm" },
    ],
    sections: [
      {
        title: "rates.policy.section.extra",
        fields: [
          { key: "extra_code", kind: "text", label: "rates.f.extra_code", required: true, help: "rates.h.extra_code" },
          { key: "extra_name", kind: "text", label: "rates.f.extra_name", required: true },
          { key: "category", kind: "select", label: "rates.f.category", options: EXTRA_CATEGORIES, group: "extra_category" },
          { key: "property", kind: "property", label: "rates.f.hotel" },
          { key: "description", kind: "textarea", label: "rates.f.description", wide: true },
        ],
      },
      {
        title: "rates.policy.section.pricing",
        help: "rates.policy.extras.pricing_help",
        fields: [
          { key: "pricing_mode", kind: "select", label: "rates.f.pricing_mode", required: true, options: EXTRA_MODES, group: "extra_mode", helpByValue: "rates.extra_mode_help" },
          { key: "currency", kind: "link", source: "currency", label: "rates.f.currency", required: true },
          { key: "amount", kind: "decimal", label: "rates.f.price_adult_unit", suffix: (d) => String(d.currency || "") },
          { key: "child_pricing", kind: "select", label: "rates.f.child_pricing", options: CHILD_PRICING, group: "child_pricing" },
          { key: "child_amount", kind: "decimal", label: "rates.f.child_amount", showIf: (d) => d.child_pricing === "CUSTOM", suffix: (d) => String(d.currency || "") },
          { key: "infant_pricing", kind: "select", label: "rates.f.infant_pricing", options: INFANT_PRICING, group: "infant_pricing" },
          { key: "infant_amount", kind: "decimal", label: "rates.f.infant_amount", showIf: (d) => d.infant_pricing === "CUSTOM", suffix: (d) => String(d.currency || "") },
          { key: "tax_category", kind: "select", label: "rates.f.tax_category", options: TAX_CATEGORIES, group: "tax_category" },
        ],
      },
      {
        title: "rates.policy.section.availability",
        fields: [
          { key: "is_mandatory", kind: "check", label: "rates.f.is_mandatory", help: "rates.h.is_mandatory" },
          { key: "bookable_online", kind: "check", label: "rates.f.bookable_online" },
          { key: "bookable_after_booking", kind: "check", label: "rates.f.bookable_after_booking", help: "rates.h.bookable_after_booking" },
          { key: "disabled", kind: "check", label: "rates.f.disabled" },
          { key: "max_quantity", kind: "int", label: "rates.f.max_quantity", help: "rates.h.zero_no_limit" },
          { key: "inventory_tracked", kind: "check", label: "rates.f.inventory_tracked", help: "rates.h.inventory_tracked" },
          { key: "daily_capacity", kind: "int", label: "rates.f.daily_capacity", help: "rates.h.daily_capacity", required: true, showIf: (d) => Boolean(d.inventory_tracked) },
          { key: "sale_from", kind: "date", label: "rates.f.sale_from" },
          { key: "sale_to", kind: "date", label: "rates.f.sale_to" },
          { key: "service_from", kind: "date", label: "rates.f.service_from" },
          { key: "service_to", kind: "date", label: "rates.f.service_to" },
          { key: "markets", kind: "csv", source: "market", label: "rates.f.markets", blank: "rates.common.all_markets" },
          { key: "channels", kind: "csv", source: "channel", label: "rates.f.channels", blank: "rates.common.all_channels" },
          { key: "room_types", kind: "csv", source: "room_type", label: "rates.f.room_types", blank: "rates.common.all_rooms" },
        ],
      },
      {
        title: "rates.policy.section.price_rules",
        help: "rates.policy.extras.rules_help",
        fields: [
          {
            key: "price_rules",
            kind: "table",
            label: "rates.policy.section.price_rules",
            columns: [
              { key: "market", kind: "select", source: "market", label: "rates.f.market", blank: "rates.common.any" },
              { key: "room_type", kind: "select", source: "room_type", label: "rates.f.room_type", blank: "rates.common.any" },
              { key: "sales_channel", kind: "select", source: "channel", label: "rates.f.channel", blank: "rates.common.any" },
              { key: "stay_from", kind: "date", label: "rates.f.stay_from" },
              { key: "stay_to", kind: "date", label: "rates.f.stay_to" },
              { key: "sale_from", kind: "date", label: "rates.f.sale_from" },
              { key: "sale_to", kind: "date", label: "rates.f.sale_to" },
              { key: "service_from", kind: "date", label: "rates.f.service_from" },
              { key: "service_to", kind: "date", label: "rates.f.service_to" },
              { key: "amount", kind: "decimal", label: "rates.f.price" },
              { key: "custom_child_amounts", kind: "check", label: "rates.f.custom_child_amounts" },
              { key: "child_amount", kind: "decimal", label: "rates.f.child_amount" },
              { key: "infant_amount", kind: "decimal", label: "rates.f.infant_amount" },
              { key: "priority", kind: "int", label: "rates.f.priority" },
            ],
          },
        ],
      },
    ],
  },
  // ─── Taxes (effective-dated, G-20) ─────────────────────────────────────
  {
    slug: "taxes",
    doctype: "TEX Tax Policy",
    cap: "tax.edit",
    revisioned: true,
    navLabel: "rates.nav.taxes",
    title: "rates.policy.taxes.title",
    singular: "rates.policy.taxes.one",
    intro: "rates.policy.taxes.intro",
    titleField: "policy_name",
    propertyRequired: true,
    newDoc: () => ({ rules: [] }),
    list: [
      { key: "policy_name", label: "rates.f.policy_name", render: "text" },
      { key: "tex_status", label: "rates.f.status", render: "status" },
      { key: "revision_no", label: "rates.f.revision", render: "rev", hideBelow: "sm" },
      { key: "active_from", label: "rates.f.active_from", render: "datetime", hideBelow: "md" },
    ],
    sections: [
      {
        title: "rates.policy.section.scope",
        fields: [
          { key: "policy_name", kind: "text", label: "rates.f.policy_name", required: true },
          { key: "property", kind: "property", label: "rates.f.hotel" },
          { key: "currency", kind: "link", source: "currency", label: "rates.f.currency_fixed", help: "rates.h.tax_currency", blank: "rates.common.hotel_currency" },
          { key: "description", kind: "textarea", label: "rates.f.description", wide: true },
        ],
      },
      {
        title: "rates.policy.taxes.rules",
        help: "rates.policy.taxes.rules_help",
        fields: [
          {
            key: "rules",
            kind: "table",
            label: "rates.policy.taxes.rules",
            columns: [
              { key: "code", kind: "text", label: "rates.f.code", required: true },
              { key: "tax_name", kind: "text", label: "rates.f.tax_name" },
              { key: "kind", kind: "select", label: "rates.f.tax_kind", options: TAX_KINDS, group: "tax_kind", required: true, default: "PERCENT" },
              { key: "rate", kind: "decimal", label: "rates.f.tax_rate" },
              { key: "amount", kind: "decimal", label: "rates.f.tax_amount" },
              { key: "applies_to", kind: "select", label: "rates.f.applies_to", options: TAX_APPLIES, group: "tax_applies", required: true, default: "ACCOMMODATION" },
              { key: "compound", kind: "check", label: "rates.f.compound", help: "rates.h.compound" },
              { key: "sort_order", kind: "int", label: "rates.f.sort_order" },
            ],
          },
        ],
      },
    ],
  },
  // ─── Allotments ─────────────────────────────────────────────────────────
  {
    slug: "allotments",
    doctype: "TEX Allotment",
    cap: "inventory.edit",
    revisioned: false,
    navLabel: "rates.nav.allotments",
    title: "rates.policy.allotments.title",
    singular: "rates.policy.allotments.one",
    intro: "rates.policy.allotments.intro",
    titleField: (d) => String(d.name || ""),
    propertyRequired: true,
    newDoc: () => ({ rooms: 1, release_days: 7, cutoff_days: 0, guaranteed: 0, disabled: 0 }),
    list: [
      { key: "room_type", label: "rates.f.room_type", render: "room" },
      { key: "contract", label: "rates.f.contract", render: "contract" },
      { key: "date_from", label: "rates.f.date_from", render: "date", hideBelow: "sm" },
      { key: "date_to", label: "rates.f.date_to", render: "date", hideBelow: "sm" },
      { key: "rooms", label: "rates.f.rooms_per_night", render: "text" },
    ],
    sections: [
      {
        title: "rates.policy.section.allotment",
        help: "rates.policy.allotments.help",
        fields: [
          { key: "property", kind: "property", label: "rates.f.hotel" },
          { key: "room_type", kind: "link", source: "room_type", label: "rates.f.room_type", required: true },
          { key: "contract", kind: "link", source: "contract", label: "rates.f.contract", required: true },
          { key: "market", kind: "link", source: "market", label: "rates.f.market", blank: "rates.common.any_market" },
          { key: "date_from", kind: "date", label: "rates.f.date_from", required: true },
          { key: "date_to", kind: "date", label: "rates.f.date_to", required: true },
          { key: "rooms", kind: "int", label: "rates.f.rooms_per_night", required: true },
          { key: "release_days", kind: "int", label: "rates.f.release_days", help: "rates.h.release_days" },
          { key: "cutoff_days", kind: "int", label: "rates.f.cutoff_days", help: "rates.h.cutoff_days" },
          { key: "guaranteed", kind: "check", label: "rates.f.guaranteed", help: "rates.h.guaranteed" },
          { key: "disabled", kind: "check", label: "rates.f.disabled" },
          { key: "note", kind: "text", label: "rates.f.note", wide: true },
        ],
      },
    ],
  },
]

export function policyKind(slug: string | undefined): PolicyKind | undefined {
  return POLICY_KINDS.find((k) => k.slug === slug)
}

export const BOARD_VALUES = BOARDS

/** Kind map of every top-level field (for normalising a loaded record). */
export function fieldKinds(k: PolicyKind): Record<string, PolicyField> {
  const out: Record<string, PolicyField> = {}
  for (const s of k.sections) for (const f of s.fields) out[f.key] = f
  return out
}
