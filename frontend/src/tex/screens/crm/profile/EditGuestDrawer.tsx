import { useMemo, useState } from "react"
import { useTexMutation } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { TEX_LANGS, useTexT } from "../../../i18n"
import { Badge, Button, Drawer, Field, FormGrid, InlineError, Input, Select, Switch, Textarea, useToast } from "../../../ui"
import { splitTags, useEvent } from "../lib"
import type { Guest } from "../types"
import { GENDER_KEYS } from "./ContactCard"
import { plainEmail } from "../../../../lib/email"

type Editable = Pick<
  Guest,
  | "first_name"
  | "last_name"
  | "phone"
  | "email"
  | "nationality"
  | "date_of_birth"
  | "gender"
  | "guest_notes"
  | "address_line"
  | "city"
  | "tex_language"
  | "tex_country"
  | "tex_market"
  | "tex_tags"
  | "tex_preferences"
  | "blacklist_reason"
> & { vip: boolean; blacklisted: boolean }

const TEXT_FIELDS = [
  "first_name",
  "last_name",
  "phone",
  "email",
  "nationality",
  "date_of_birth",
  "gender",
  "guest_notes",
  "address_line",
  "city",
  "tex_language",
  "tex_country",
  "tex_market",
  "tex_tags",
  "tex_preferences",
  "blacklist_reason",
] as const

function fromGuest(g: Guest): Editable {
  const out = { vip: Boolean(g.vip), blacklisted: Boolean(g.blacklisted) } as Editable
  for (const f of TEXT_FIELDS) (out as Record<string, unknown>)[f] = g[f] ?? ""
  return out
}

// Common Frappe Country names (the field links to Country; any valid name works).
const COUNTRIES = ["Turkey", "Germany", "Austria", "Switzerland", "United Kingdom", "Netherlands", "Poland", "Romania", "Russia", "Ukraine", "Kazakhstan", "France", "Italy", "Spain", "United States"]

export function EditGuestDrawer({ guest, open, onClose, onSaved }: { guest: Guest; open: boolean; onClose: () => void; onSaved: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  // mounted per opening (GuestProfile): the form starts from the guest as the drawer opens (2Z)
  const [form, setForm] = useState<Editable>(() => fromGuest(guest))
  const save = useTexMutation<{ name: string; data: Record<string, unknown> }, { changed: string[] }>("crm", "update_guest")
  const close = useEvent(() => {
    if (!save.pending) onClose()
  })

  const initial = useMemo(() => fromGuest(guest), [guest])
  const diff = useMemo(() => {
    const d: Record<string, unknown> = {}
    for (const f of TEXT_FIELDS) if ((form[f] ?? "") !== (initial[f] ?? "")) d[f] = form[f] ?? ""
    if (form.vip !== initial.vip) d.vip = form.vip ? 1 : 0
    if (form.blacklisted !== initial.blacklisted) d.blacklisted = form.blacklisted ? 1 : 0
    return d
  }, [form, initial])

  const set = <K extends keyof Editable>(k: K, v: Editable[K]) => setForm((f) => ({ ...f, [k]: v }))
  // one plain address, as the server keeps it (2P review round 1): İNFO@… would never be joined by a booking (ADR-080)
  const emailBad = Boolean((form.email ?? "").trim()) && !plainEmail(form.email)
  const nameMissing = !(form.first_name ?? "").trim()
  const reasonMissing = form.blacklisted && !(form.blacklist_reason ?? "").trim()
  const invalid = emailBad || nameMissing || reasonMissing
  const tags = splitTags(form.tex_tags)
  const langs: { value: string; label: string }[] = TEX_LANGS.map((l) => ({ value: l.code, label: l.label }))
  if (form.tex_language && !langs.some((l) => l.value === form.tex_language)) langs.push({ value: form.tex_language, label: form.tex_language })

  const submit = async () => {
    if (invalid || !Object.keys(diff).length) return
    try {
      await save.run({ name: guest.name, data: diff })
      toast.success(t("crm.edit.saved"))
      onSaved()
      onClose()
    } catch {
      /* shown inline */
    }
  }

  return (
    <Drawer
      open={open}
      onClose={close}
      title={t("crm.edit.title")}
      width="lg"
      footer={
        <>
          <Button variant="secondary" onClick={close}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={save.pending} disabled={invalid || !Object.keys(diff).length} onClick={submit}>
            {t("core.action.save")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-6"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <fieldset className="space-y-4">
          <legend className="mb-2 text-sm font-semibold text-zinc-900">{t("crm.edit.identity")}</legend>
          <FormGrid>
            <Field label={t("crm.field.first_name")} required error={nameMissing ? t("crm.edit.required") : undefined}>
              <Input value={form.first_name ?? ""} onChange={(e) => set("first_name", e.target.value)} autoComplete="off" data-autofocus />
            </Field>
            <Field label={t("crm.field.last_name")}>
              <Input value={form.last_name ?? ""} onChange={(e) => set("last_name", e.target.value)} autoComplete="off" />
            </Field>
            <Field label={t("crm.field.email")} error={emailBad ? t("crm.edit.email_invalid") : undefined}>
              <Input type="email" value={form.email ?? ""} onChange={(e) => set("email", e.target.value)} autoComplete="off" />
            </Field>
            <Field label={t("crm.field.phone")} hint={t("crm.edit.phone_hint")}>
              <Input type="tel" value={form.phone ?? ""} onChange={(e) => set("phone", e.target.value)} autoComplete="off" />
            </Field>
            <Field label={t("crm.field.dob")}>
              <Input type="date" value={form.date_of_birth ?? ""} onChange={(e) => set("date_of_birth", e.target.value)} />
            </Field>
            <Field label={t("crm.field.gender")}>
              <Select
                value={form.gender ?? ""}
                onChange={(e) => set("gender", e.target.value)}
                options={[{ value: "", label: "—" }, ...Object.entries(GENDER_KEYS).map(([v, k]) => ({ value: v, label: t(k) }))]}
              />
            </Field>
          </FormGrid>
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="mb-2 text-sm font-semibold text-zinc-900">{t("crm.edit.market_language")}</legend>
          <FormGrid>
            <Field label={t("crm.field.language")} hint={t("crm.edit.language_hint")}>
              <Select value={form.tex_language ?? ""} onChange={(e) => set("tex_language", e.target.value)} options={[{ value: "", label: "—" }, ...langs]} />
            </Field>
            <Field label={t("crm.field.market")}>
              <Select
                value={form.tex_market ?? ""}
                onChange={(e) => set("tex_market", e.target.value)}
                options={[{ value: "", label: "—" }, ...boot.markets.map((m) => ({ value: m.name, label: `${m.market_name} (${m.name})` }))]}
              />
            </Field>
            <Field label={t("crm.field.country")} hint={t("crm.edit.country_hint")}>
              <Input list="crm-countries" value={form.tex_country ?? ""} onChange={(e) => set("tex_country", e.target.value)} autoComplete="off" />
            </Field>
            <Field label={t("crm.field.nationality")}>
              <Input value={form.nationality ?? ""} onChange={(e) => set("nationality", e.target.value)} autoComplete="off" />
            </Field>
            <Field label={t("crm.field.address_line")}>
              <Input value={form.address_line ?? ""} onChange={(e) => set("address_line", e.target.value)} autoComplete="off" />
            </Field>
            <Field label={t("crm.field.city")}>
              <Input value={form.city ?? ""} onChange={(e) => set("city", e.target.value)} autoComplete="off" />
            </Field>
          </FormGrid>
          <datalist id="crm-countries">
            {COUNTRIES.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="mb-2 text-sm font-semibold text-zinc-900">{t("crm.edit.relationship")}</legend>
          <Switch checked={form.vip} onChange={(v) => set("vip", v)} label={t("crm.field.vip")} description={t("crm.edit.vip_hint")} />
          <Field label={t("crm.field.tags")} hint={t("crm.edit.tags_hint")}>
            <Input value={form.tex_tags ?? ""} onChange={(e) => set("tex_tags", e.target.value)} autoComplete="off" />
          </Field>
          {tags.length > 0 && (
            <ul className="-mt-2 flex flex-wrap gap-1.5" aria-label={t("crm.field.tags")}>
              {tags.map((tg) => (
                <li key={tg}>
                  <Badge>{tg}</Badge>
                </li>
              ))}
            </ul>
          )}
          <Field label={t("crm.field.preferences")} hint={t("crm.edit.preferences_hint")}>
            <Textarea value={form.tex_preferences ?? ""} onChange={(e) => set("tex_preferences", e.target.value)} rows={3} />
          </Field>
          <Field label={t("crm.field.notes")} hint={t("crm.edit.notes_hint")}>
            <Textarea value={form.guest_notes ?? ""} onChange={(e) => set("guest_notes", e.target.value)} rows={3} />
          </Field>
        </fieldset>

        <fieldset className="space-y-4 rounded-lg border border-zinc-200 p-3">
          <legend className="px-1 text-sm font-semibold text-zinc-900">{t("crm.edit.blacklist")}</legend>
          <Switch
            checked={form.blacklisted}
            onChange={(v) => set("blacklisted", v)}
            label={t("crm.field.blacklisted")}
            description={t("crm.edit.blacklist_hint")}
          />
          {form.blacklisted && (
            <Field label={t("crm.field.blacklist_reason")} required error={reasonMissing ? t("crm.edit.required") : undefined}>
              <Textarea value={form.blacklist_reason ?? ""} onChange={(e) => set("blacklist_reason", e.target.value)} rows={2} />
            </Field>
          )}
        </fieldset>
        <p className="text-xs text-zinc-500">{t("crm.edit.audit_hint")}</p>
        <InlineError error={save.error} />
        <button type="submit" className="hidden" aria-hidden tabIndex={-1} />
      </form>
    </Drawer>
  )
}
