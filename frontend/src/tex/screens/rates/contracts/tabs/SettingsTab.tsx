import { useTexT } from "../../../../i18n"
import { useSession } from "../../../../lib/session"
import { DescriptionList, Field, FormGrid, Select, Switch, Textarea } from "../../../../ui"
import { AGE_BASIS, CHILD_ORDERING, enumLabel, enumOptions, EXTRA_UNIT, STACKING } from "../../lib/options"
import { TabIntro, TabIssues, type TabProps } from "./shared"

/** Version-wide engine settings (child ordering, age basis, stacking, room-basis options). */
export function SettingsTab({ doc, state, readOnly, issues, setSetting }: TabProps) {
  const { t } = useTexT()
  const { boot } = useSession()
  const s = state.settings
  const room = doc.contract_doc.pricing_basis === "ROOM"
  return (
    <div className="space-y-5">
      <TabIntro title={t("rates.tab.settings")}>{t("rates.settings.intro")}</TabIntro>
      <TabIssues issues={issues} tab="settings" />
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
