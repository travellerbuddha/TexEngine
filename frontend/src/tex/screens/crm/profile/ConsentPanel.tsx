import { useEffect, useMemo, useState } from "react"
import { ShieldCheck } from "lucide-react"
import { useTexMutation } from "../../../lib/api"
import { dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, Checkbox, Dialog, Field, InlineError, Input, Notice, Select, useToast } from "../../../ui"
import { ConsentIcon, consentLabelKey } from "../components/common"
import { safeJson, useEvent } from "../lib"
import { CONSENT_FIELDS, type ConsentEvent, type ConsentField, type Guest } from "../types"

/** How the guest expressed the choice. Stored verbatim in tex_consent_source and
 * as the reason of the audit event, so values stay stable (labels are translated). */
export const CONSENT_SOURCES = ["phone", "in_person", "written_form", "email", "booking_form", "guest_portal"] as const

function sourceLabel(t: (k: string) => string, s: string | null | undefined) {
  if (!s) return "—"
  return (CONSENT_SOURCES as readonly string[]).includes(s) || s === "staff" || s === "booking" ? t(`crm.consent.source.${s}`) : s
}

type Consents = Record<ConsentField, boolean>

function current(g: Guest): Consents {
  return { tex_consent_email: Boolean(g.tex_consent_email), tex_consent_sms: Boolean(g.tex_consent_sms), tex_consent_whatsapp: Boolean(g.tex_consent_whatsapp) }
}

export function ConsentPanel({ guest, history, canEdit, onSaved }: { guest: Guest; history: ConsentEvent[]; canEdit: boolean; onSaved: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const base = useMemo(() => current(guest), [guest])
  const [draft, setDraft] = useState<Consents>(base)
  const [confirming, setConfirming] = useState(false)
  const [source, setSource] = useState("")
  const [version, setVersion] = useState("")
  const [ack, setAck] = useState(false)
  const save = useTexMutation<{ name: string; data: Record<string, number>; consent_source: string; consent_text_version?: string }>("crm", "update_guest")

  useEffect(() => setDraft(base), [base])
  const closeDialog = useEvent(() => {
    if (!save.pending) setConfirming(false)
  })
  const changed = CONSENT_FIELDS.filter((f) => draft[f] !== base[f])
  const granting = changed.some((f) => draft[f])

  const open = () => {
    setSource("")
    setVersion(guest.tex_consent_text_version ?? "")
    setAck(false)
    save.clearError()
    setConfirming(true)
  }
  const valid = Boolean(source) && ack && (!granting || version.trim().length > 0)

  const submit = async () => {
    if (!valid) return
    const data: Record<string, number> = {}
    for (const f of changed) data[f] = draft[f] ? 1 : 0
    try {
      await save.run({ name: guest.name, data, consent_source: source, consent_text_version: version.trim() || undefined })
      toast.success(t("crm.consent.saved"))
      setConfirming(false)
      onSaved()
    } catch {
      /* inline */
    }
  }

  return (
    <Card>
      <CardHeader
        title={t("crm.consent.title")}
        description={t("crm.consent.subtitle")}
        actions={<ShieldCheck className="size-4 text-zinc-400" aria-hidden />}
      />
      <CardBody className="space-y-4">
        <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
          {CONSENT_FIELDS.map((f) => {
            const label = t(consentLabelKey(f))
            const on = draft[f]
            const dirty = on !== base[f]
            return (
              <li key={f} className="flex items-center justify-between gap-3 px-3 py-2.5">
                <div className="flex min-w-0 items-center gap-2.5">
                  <span className="rounded-md bg-zinc-100 p-1.5 text-zinc-600">
                    <ConsentIcon field={f} className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-zinc-900">{t("crm.consent.marketing_by", { channel: label })}</p>
                    <p className="text-xs text-zinc-500">
                      {on ? t("crm.consent.state_granted") : t("crm.consent.state_not_granted")}
                      {dirty && <span className="ml-1 font-medium text-amber-700">· {t("crm.consent.unsaved")}</span>}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={on}
                  aria-label={t("crm.consent.toggle", { channel: label })}
                  disabled={!canEdit}
                  onClick={() => setDraft((d) => ({ ...d, [f]: !d[f] }))}
                  className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${on ? "bg-tex-600" : "bg-zinc-300"}`}
                >
                  <span className={`inline-block size-5 rounded-full bg-white shadow transition-transform ${on ? "translate-x-5.5" : "translate-x-0.5"}`} />
                </button>
              </li>
            )
          })}
        </ul>

        {changed.length > 0 && (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDraft(base)}>
              {t("core.action.reset")}
            </Button>
            <Button size="sm" onClick={open}>
              {t("crm.consent.record", { count: changed.length })}
            </Button>
          </div>
        )}

        <dl className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
          <div>
            <dt className="text-zinc-500">{t("crm.consent.updated_at")}</dt>
            <dd className="text-zinc-900">{dateTime(guest.tex_consent_updated_at)}</dd>
          </div>
          <div>
            <dt className="text-zinc-500">{t("crm.consent.source")}</dt>
            <dd className="text-zinc-900">{sourceLabel(t, guest.tex_consent_source)}</dd>
          </div>
          <div>
            <dt className="text-zinc-500">{t("crm.consent.text_version")}</dt>
            <dd className="break-all text-zinc-900">{guest.tex_consent_text_version || "—"}</dd>
          </div>
        </dl>

        <details className="group rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-600">
          <summary className="cursor-pointer font-medium text-zinc-800">{t("crm.consent.legal_title")}</summary>
          <div className="mt-2 space-y-1.5">
            <p>{t("crm.consent.legal_1")}</p>
            <p>{t("crm.consent.legal_2")}</p>
            <p>{t("crm.consent.legal_3")}</p>
          </div>
        </details>

        <div>
          <h3 className="text-xs font-semibold tracking-wide text-zinc-600 uppercase">{t("crm.consent.history")}</h3>
          {history.length ? (
            <ol className="mt-2 space-y-2">
              {history.map((h, i) => {
                const changes = safeJson<Record<string, boolean>>(h.new_value, {})
                return (
                  <li key={i} className="rounded-lg border border-zinc-100 px-3 py-2 text-xs">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {Object.entries(changes).map(([f, v]) => (
                        <Badge key={f} tone={v ? "success" : "neutral"}>
                          {(CONSENT_FIELDS as readonly string[]).includes(f) ? t(consentLabelKey(f as ConsentField)) : f}:{" "}
                          {v ? t("crm.consent.granted") : t("crm.consent.withdrawn")}
                        </Badge>
                      ))}
                    </div>
                    <p className="mt-1 text-zinc-500">
                      {dateTime(h.event_time)} · {h.actor === "Guest" ? t("crm.actor.guest") : h.actor} · {sourceLabel(t, h.reason)}
                    </p>
                  </li>
                )
              })}
            </ol>
          ) : (
            <p className="mt-1 text-xs text-zinc-500">{t("crm.consent.no_history")}</p>
          )}
        </div>
      </CardBody>

      <Dialog
        open={confirming}
        onClose={closeDialog}
        title={t("crm.consent.confirm_title")}
        description={t("crm.consent.confirm_desc")}
        footer={
          <>
            <Button variant="secondary" onClick={closeDialog} disabled={save.pending}>
              {t("core.action.cancel")}
            </Button>
            <Button loading={save.pending} disabled={!valid} onClick={submit}>
              {t("crm.consent.confirm_save")}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <ul className="space-y-1 text-sm">
            {changed.map((f) => (
              <li key={f} className="flex items-center gap-2">
                <ConsentIcon field={f} className="size-4 text-zinc-500" />
                <span className="font-medium">{t(consentLabelKey(f))}:</span>
                <Badge tone={draft[f] ? "success" : "warning"}>{draft[f] ? t("crm.consent.will_grant") : t("crm.consent.will_withdraw")}</Badge>
              </li>
            ))}
          </ul>
          <Field label={t("crm.consent.source_label")} required hint={t("crm.consent.source_hint")}>
            <Select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder={t("crm.consent.source_pick")}
              options={CONSENT_SOURCES.map((s) => ({ value: s, label: t(`crm.consent.source.${s}`) }))}
              data-autofocus
            />
          </Field>
          <Field
            label={t("crm.consent.text_version_label")}
            required={granting}
            hint={granting ? t("crm.consent.text_version_hint_grant") : t("crm.consent.text_version_hint")}
          >
            <Input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="KVKK-2026-01" autoComplete="off" maxLength={140} />
          </Field>
          <Checkbox
            checked={ack}
            onChange={(e) => setAck(e.target.checked)}
            label={granting ? t("crm.consent.ack_grant") : t("crm.consent.ack_withdraw")}
            className="items-start [&>input]:mt-0.5"
          />
          {granting && <Notice tone="info">{t("crm.consent.transactional_note")}</Notice>}
          <InlineError error={save.error} />
        </div>
      </Dialog>
    </Card>
  )
}
