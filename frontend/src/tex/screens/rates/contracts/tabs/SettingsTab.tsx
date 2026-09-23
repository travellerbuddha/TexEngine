import { useTexT } from "../../../../i18n"
import { useSession } from "../../../../lib/session"
import { DescriptionList, Field, FormGrid, Input, Notice, Select, Switch, Textarea } from "../../../../ui"
import { CsvPicker } from "../../components/pickers"
import { DateRange } from "../../components/common"
import { AGE_BASIS, CHILD_ORDERING, enumLabel, enumOptions, EXTRA_UNIT, STACKING } from "../../lib/options"
import { TabIntro, TabIssues, type TabProps } from "./shared"

/** Version-wide engine settings (child ordering, age basis, stacking, room-basis options). */
export function SettingsTab(props: TabProps) {
  const { doc, state, readOnly, issues, setSetting } = props
  const { t } = useTexT()
  const { boot } = useSession()
  const s = state.settings
  const room = doc.contract_doc.pricing_basis === "ROOM"
  return (
    <div className="space-y-5">
      <TabIntro title={t("rates.tab.settings")}>{t("rates.settings.intro")}</TabIntro>
      <TabIssues issues={issues} tab="settings" />
      <SellingTerms {...props} />
      <div className="rounded-lg border border-zinc-200 bg-zinc-50/60 p-4">
        <DescriptionList
          cols={3}
          items={[
            { label: t("rates.f.pricing_basis"), value: `${enumLabel(t, "basis", doc.contract_doc.pricing_basis)} — ${t(`rates.basis_help.${doc.contract_doc.pricing_basis}`)}` },
            { label: t("rates.f.contract_currency"), value: doc.contract_doc.contract_currency },
            { label: t("rates.f.market"), value: `${doc.contract_doc.market} · ${boot.markets.find((m) => m.name === doc.contract_doc.market)?.market_name ?? ""}` },
          ]}
        />
      </div>
      <FormGrid cols={2}>
        <Field label={t("rates.f.child_ordering")} hint={t("rates.h.child_ordering")}>
          <Select disabled={readOnly} value={String(s.child_ordering)} onChange={(e) => setSetting("child_ordering", e.target.value)} options={enumOptions(t, "child_ordering", CHILD_ORDERING)} />
        </Field>
        <Field label={t("rates.f.age_basis")} hint={t("rates.h.age_basis")}>
          <Select disabled={readOnly} value={String(s.age_basis)} onChange={(e) => setSetting("age_basis", e.target.value)} options={enumOptions(t, "age_basis", AGE_BASIS)} />
        </Field>
        <Field label={t("rates.f.stacking")} hint={t(`rates.h.stacking.${s.stacking}`)}>
          <Select disabled={readOnly} value={String(s.stacking)} onChange={(e) => setSetting("stacking", e.target.value)} options={enumOptions(t, "stacking", STACKING)} />
        </Field>
        {room && (
          <Field label={t("rates.f.room_basis_extra_unit")} hint={t(`rates.h.extra_unit.${s.room_basis_extra_unit}`)}>
            <Select disabled={readOnly} value={String(s.room_basis_extra_unit)} onChange={(e) => setSetting("room_basis_extra_unit", e.target.value)} options={enumOptions(t, "extra_unit", EXTRA_UNIT)} />
          </Field>
        )}
      </FormGrid>
      <div className="max-w-2xl space-y-4 rounded-lg border border-zinc-200 p-4">
        <Switch
          disabled={readOnly}
          checked={Boolean(s.children_over_max_as_adults)}
          onChange={(v) => setSetting("children_over_max_as_adults", v ? 1 : 0)}
          label={t("rates.f.children_over_max_as_adults")}
          description={t("rates.h.children_over_max_as_adults")}
        />
        <Switch
          disabled={readOnly}
          checked={Boolean(s.infants_count_as_occupants)}
          onChange={(v) => setSetting("infants_count_as_occupants", v ? 1 : 0)}
          label={t("rates.f.infants_count_as_occupants")}
          description={t("rates.h.infants_count_as_occupants")}
        />
        <Switch
          disabled={readOnly}
          checked={Boolean(s.prices_include_tax)}
          onChange={(v) => setSetting("prices_include_tax", v ? 1 : 0)}
          label={t("rates.f.prices_include_tax")}
          description={t("rates.h.prices_include_tax")}
        />
        {room && (
          <Switch
            disabled={readOnly}
            checked={Boolean(s.room_basis_children_fill_included)}
            onChange={(v) => setSetting("room_basis_children_fill_included", v ? 1 : 0)}
            label={t("rates.f.room_basis_children_fill_included")}
            description={t("rates.h.room_basis_children_fill_included")}
          />
        )}
      </div>
      <Field label={t("rates.f.change_note")} hint={t("rates.h.change_note_draft")} className="max-w-2xl">
        <Textarea disabled={readOnly} value={String(s.change_note ?? "")} onChange={(e) => setSetting("change_note", e.target.value)} rows={3} maxLength={500} />
      </Field>
    </div>
  )
}

/** When, where and in which order this version sells (G-50, ADR-045): a draft of a published
 * contract edits its own; a published version shows what it froze; before the contract's first
 * publish they come from the contract header. */
function SellingTerms({ doc, state, readOnly, setSelling }: TabProps) {
  const { t } = useTexT()
  const { boot } = useSession()
  const g = state.selling
  const v = doc.selling
  if (!v) return null
  const channelOpts = boot.channels.map((c) => ({ value: c.name, label: c.channel_name }))
  const ccyOpts = boot.currencies.map((c) => ({ value: c, label: c }))
  const channelNames = (codes: string[]) =>
    codes.length ? codes.map((x) => boot.channels.find((ch) => ch.name === x)?.channel_name ?? x).join(", ") : t("rates.common.all_channels")
  const saleBad = Boolean(g && g.sale_from && g.sale_to && g.sale_from > g.sale_to)
  const stayBad = Boolean(g && g.stay_from && g.stay_to && g.stay_from > g.stay_to)
  const hint =
    doc.selling_source === "header"
      ? t("rates.selling.from_header")
      : doc.selling_source === "frozen"
        ? t("rates.selling.frozen")
        : t("rates.selling.intro_version")
  return (
    <section aria-labelledby="selling-terms" className="space-y-3 rounded-lg border border-zinc-200 p-4">
      <div className="space-y-1">
        <h3 id="selling-terms" className="text-sm font-semibold text-zinc-900">
          {t("rates.selling.title")}
        </h3>
        <p className="text-xs text-zinc-500">{hint}</p>
      </div>
      {g && !readOnly ? (
        <>
          <FormGrid cols={4}>
            <Field label={t("rates.f.sale_from")}>
              <Input type="date" value={g.sale_from} onChange={(e) => setSelling({ sale_from: e.target.value })} />
            </Field>
            <Field label={t("rates.f.sale_to")} error={saleBad ? t("rates.v.range") : undefined}>
              <Input type="date" value={g.sale_to} onChange={(e) => setSelling({ sale_to: e.target.value })} />
            </Field>
            <Field label={t("rates.f.stay_from")}>
              <Input type="date" value={g.stay_from} onChange={(e) => setSelling({ stay_from: e.target.value })} />
            </Field>
            <Field label={t("rates.f.stay_to")} error={stayBad ? t("rates.v.range") : undefined}>
              <Input type="date" value={g.stay_to} onChange={(e) => setSelling({ stay_to: e.target.value })} />
            </Field>
          </FormGrid>
          <FormGrid cols={3}>
            <Field label={t("rates.f.priority")} hint={t("rates.h.contract_priority")}>
              <Input type="number" step={1} value={String(g.priority)} onChange={(e) => setSelling({ priority: parseInt(e.target.value || "0", 10) || 0 })} />
            </Field>
            <Field label={t("rates.f.sell_currency")} hint={t("rates.h.sell_currency")}>
              <Select value={g.sell_currency} onChange={(e) => setSelling({ sell_currency: e.target.value })} options={ccyOpts} placeholder={t("rates.common.same_as_contract")} />
            </Field>
            <Field label={t("rates.f.channels")} hint={t("rates.h.channels")}>
              <CsvPicker value={g.channels} onChange={(c) => setSelling({ channels: c })} options={channelOpts} label={t("rates.f.channels")} allLabel={t("rates.common.all_channels")} />
            </Field>
          </FormGrid>
        </>
      ) : (
        <>
          <DescriptionList
            cols={3}
            items={[
              { label: t("rates.col.sale_window"), value: <DateRange from={v.sale_from} to={v.sale_to} /> },
              { label: t("rates.col.stay_window"), value: <DateRange from={v.stay_from} to={v.stay_to} /> },
              { label: t("rates.f.channels"), value: channelNames(v.channels) },
              { label: t("rates.f.priority"), value: String(v.priority ?? 0) },
              { label: t("rates.f.sell_currency"), value: v.sell_currency || t("rates.common.same_as_contract") },
            ]}
          />
          {doc.selling_source === "header" && <Notice tone="info">{t("rates.selling.edit_in_header")}</Notice>}
        </>
      )}
    </section>
  )
}
