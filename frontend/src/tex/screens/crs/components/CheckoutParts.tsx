import { forwardRef } from "react"
import { Link2Off, Star } from "lucide-react"
import { TEX_LANGS, useTexT } from "../../../i18n"
import { Badge, Button, Checkbox, Field, FormGrid, Input, Money, Notice, Select, Skeleton, Textarea } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { useLabels } from "../lib/labels"
import type { BookingFlow } from "../lib/useBookingFlow"
import { Row } from "./controls"
import { GuestLookup } from "./GuestLookup"

/** Staying guest, booker and explicit consent (unchecked by default, never implied). */
export const GuestForm = forwardRef<
  HTMLInputElement,
  { flow: BookingFlow; lookup?: boolean; idPrefix?: string; canLookup?: boolean }
>(function GuestForm({ flow, lookup = true, idPrefix = "g", canLookup = true }, firstRef) {
  const { t } = useTexT()
  const { guest, setGuest, booker, setBooker, guestErrors: e } = flow
  const g = guest.crm_guest
  const already = g
    ? [g.tex_consent_email ? t("crs.consent.email") : null, g.tex_consent_sms ? t("crs.consent.sms") : null, g.tex_consent_whatsapp ? t("crs.consent.whatsapp") : null].filter(Boolean)
    : []
  return (
    <div className="space-y-4">
      {lookup && canLookup && (
        <GuestLookup
          ref={firstRef}
          id={`${idPrefix}-lookup`}
          label={t("crs.guest.lookup")}
          placeholder={t("crs.guest.lookup_placeholder")}
          onPick={flow.applyGuest}
        />
      )}
      {g && (
        <div className="flex flex-wrap items-start justify-between gap-2 rounded-lg border border-tex-200 bg-tex-50 px-3 py-2 text-sm">
          <div>
            <p className="flex items-center gap-1.5 font-medium text-tex-900">
              {t("crs.guest.linked", { name: g.full_name })}
              {g.vip ? <Star className="size-3.5 fill-amber-600 text-amber-600" aria-label={t("crs.guest.vip")} /> : null}
            </p>
            <p className="text-xs text-tex-800">
              {t("crs.guest.stays", { count: g.tex_stays ?? 0 })}
              {already.length ? ` · ${t("crs.consent.already", { list: already.join(", ") })}` : ""}
            </p>
          </div>
          <Button variant="ghost" size="sm" icon={<Link2Off className="size-4" aria-hidden />} onClick={() => flow.applyGuest(null)}>
            {t("crs.guest.unlink")}
          </Button>
        </div>
      )}
      {g?.blacklisted ? <Notice tone="danger">{t("crs.guest.blacklisted_note")}</Notice> : null}
      <FormGrid cols={2}>
        <Field label={t("crs.guest.first_name")} error={e.first_name} required>
          <Input
            ref={lookup && canLookup ? undefined : firstRef}
            id={`${idPrefix}-first`}
            autoComplete="off"
            value={guest.first_name}
            onChange={(ev) => setGuest({ ...guest, first_name: ev.target.value })}
          />
        </Field>
        <Field label={t("crs.guest.last_name")} error={e.last_name} required>
          <Input id={`${idPrefix}-last`} autoComplete="off" value={guest.last_name} onChange={(ev) => setGuest({ ...guest, last_name: ev.target.value })} />
        </Field>
        <Field label={t("crs.guest.email")} error={e.email ?? e.contact} hint={!e.email && !e.contact ? t("crs.guest.contact_hint") : undefined}>
          <Input id={`${idPrefix}-email`} type="email" autoComplete="off" value={guest.email} onChange={(ev) => setGuest({ ...guest, email: ev.target.value })} />
        </Field>
        <Field label={t("crs.guest.phone")}>
          <Input id={`${idPrefix}-phone`} type="tel" autoComplete="off" value={guest.phone} onChange={(ev) => setGuest({ ...guest, phone: ev.target.value })} />
        </Field>
        <Field label={t("crs.guest.language")} hint={t("crs.guest.language_hint")}>
          <Select
            id={`${idPrefix}-lang`}
            value={guest.language}
            options={TEX_LANGS.map((l) => ({ value: l.code, label: l.label }))}
            onChange={(ev) => setGuest({ ...guest, language: ev.target.value })}
          />
        </Field>
        <Field label={t("crs.guest.requests")}>
          <Textarea id={`${idPrefix}-req`} rows={1} value={guest.special_requests} onChange={(ev) => setGuest({ ...guest, special_requests: ev.target.value })} />
        </Field>
      </FormGrid>

      <fieldset className="space-y-1.5">
        <legend className="text-sm font-medium text-zinc-800">{t("crs.consent.title")}</legend>
        <p className="text-xs text-zinc-500">{t("crs.consent.hint")}</p>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <Checkbox label={t("crs.consent.email")} checked={guest.consent_email} onChange={(ev) => setGuest({ ...guest, consent_email: ev.target.checked })} />
          <Checkbox label={t("crs.consent.sms")} checked={guest.consent_sms} onChange={(ev) => setGuest({ ...guest, consent_sms: ev.target.checked })} />
          <Checkbox
            label={t("crs.consent.whatsapp")}
            checked={guest.consent_whatsapp}
            onChange={(ev) => setGuest({ ...guest, consent_whatsapp: ev.target.checked })}
          />
        </div>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-zinc-800">{t("crs.booker.title")}</legend>
        <Checkbox label={t("crs.booker.same")} checked={booker.same} onChange={(ev) => setBooker({ ...booker, same: ev.target.checked })} />
        {!booker.same && (
          <FormGrid cols={3}>
            <Field label={t("crs.booker.name")} error={e.booker_name} required>
              <Input id={`${idPrefix}-bk-name`} value={booker.name} onChange={(ev) => setBooker({ ...booker, name: ev.target.value })} />
            </Field>
            <Field label={t("crs.guest.email")} error={e.booker_email ?? e.booker_contact}>
              <Input id={`${idPrefix}-bk-email`} type="email" value={booker.email} onChange={(ev) => setBooker({ ...booker, email: ev.target.value })} />
            </Field>
            <Field label={t("crs.guest.phone")}>
              <Input id={`${idPrefix}-bk-phone`} type="tel" value={booker.phone} onChange={(ev) => setBooker({ ...booker, phone: ev.target.value })} />
            </Field>
          </FormGrid>
        )}
      </fieldset>
    </div>
  )
})

/** Payment method (from crs.payment_methods) with the server's amount due now. */
export function PaymentPicker({
  flow,
  canConfirmUnpaid,
  idPrefix = "pay",
  showNotes = true,
}: {
  flow: BookingFlow
  canConfirmUnpaid: boolean
  idPrefix?: string
  showNotes?: boolean
}) {
  const { t } = useTexT()
  const L = useLabels()
  const { methods, methodsError, method, setMethod, summary, summaryLoading, summaryError } = flow
  const ccy = summary?.currency ?? flow.quoteCurrency ?? undefined
  return (
    <div className="space-y-4">
      <fieldset>
        <legend className="mb-1.5 text-sm font-medium text-zinc-800">
          {t("crs.pay.method")}
          {methods && methods.length > 0 && <span className="ml-0.5 text-rose-600" aria-hidden>*</span>}
        </legend>
        {methodsError ? (
          <Notice tone="danger">{methodsError.message}</Notice>
        ) : !methods ? (
          <Skeleton className="h-16 w-full" />
        ) : methods.length === 0 ? (
          <Notice tone="warning">{t("crs.pay.no_methods")}</Notice>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t("crs.pay.method")}>
            {methods.map((m) => {
              const blocked = m.method === "Pay at Hotel" && summary && !summary.pay_at_hotel_allowed
              const id = `${idPrefix}-m-${m.method.replace(/\W+/g, "-")}`
              return (
                <label
                  key={m.method}
                  htmlFor={id}
                  className={cn(
                    "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 text-sm transition-colors",
                    method === m.method ? "border-tex-500 bg-tex-50" : "border-zinc-200 bg-white hover:border-zinc-300",
                    blocked && "cursor-not-allowed opacity-60",
                  )}
                >
                  <input
                    id={id}
                    type="radio"
                    name={`${idPrefix}-method`}
                    className="mt-0.5 size-4 accent-tex-600"
                    checked={method === m.method}
                    disabled={Boolean(blocked)}
                    onChange={() => setMethod(m.method)}
                  />
                  <span className="min-w-0">
                    <span className="block font-medium text-zinc-900">{L.method(m.method)}</span>
                    <span className="block text-xs text-zinc-500">
                      {m.label !== m.method ? m.label : ""}
                      {m.sandbox ? (
                        <Badge tone="warning" className="ml-1">
                          {t("crs.pay.sandbox")}
                        </Badge>
                      ) : null}
                      {blocked ? t("crs.pay.pah_not_allowed") : null}
                    </span>
                  </span>
                </label>
              )
            })}
          </div>
        )}
        {flow.guestErrors.method && (
          <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
            {flow.guestErrors.method}
          </p>
        )}
      </fieldset>

      <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2" aria-live="polite">
        {summaryError ? (
          <p className="text-sm text-rose-700" role="alert">
            {summaryError.message}
          </p>
        ) : !summary || summaryLoading ? (
          <div className="space-y-1.5 py-1">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : (
          <>
            <Row strong label={t("crs.quote.total")} value={<Money amount={summary.total} currency={ccy} />} />
            <Row
              label={method ? t("crs.pay.due_now_method", { method: L.method(method) }) : t("crs.pay.due_now")}
              value={summary.due_now !== null ? <Money amount={summary.due_now} currency={ccy} /> : "—"}
            />
            {summary.balance_after !== null && <Row label={t("crs.pay.balance_later")} value={<Money amount={summary.balance_after} currency={ccy} />} />}
            {!summary.usable && (
              <p className="mt-1 text-xs font-medium text-rose-700" role="alert">
                {summary.rooms.find((r) => r.problem)?.problem}
              </p>
            )}
          </>
        )}
      </div>

      {canConfirmUnpaid && summary?.payment_required && (
        <Checkbox
          label={
            <span>
              {t("crs.pay.confirm_unpaid")}
              <span className="block text-xs text-zinc-500">{t("crs.pay.confirm_unpaid_hint")}</span>
            </span>
          }
          className="items-start"
          checked={flow.confirmUnpaid}
          onChange={(ev) => flow.setConfirmUnpaid(ev.target.checked)}
        />
      )}
      {showNotes && (
        <Field label={t("crs.pay.notes")} hint={t("crs.pay.notes_hint")}>
          <Textarea id={`${idPrefix}-notes`} rows={2} value={flow.notes} onChange={(ev) => flow.setNotes(ev.target.value)} />
        </Field>
      )}
    </div>
  )
}
