import { useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { ChevronLeft, ChevronRight, Link2, Plus, RefreshCw } from "lucide-react"
import { tex, useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { dateTime } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Button, Card, DataTable, EmptyState, ErrorState, Field, Input, Money, PageHeader, Select, Toolbar, useToast } from "../../ui"
import { MethodLabel, PaymentsNav, TxnStatusBadge } from "./components/common"
import { ManualPaymentDialog } from "./ManualPaymentDialog"
import { methodKey, statusKey, typeKey, useDebounced, useEvent } from "./lib"
import { TXN_METHODS, TXN_STATUSES, type Txn } from "./types"

const PAGE = 50

export default function Transactions() {
  const { t } = useTexT()
  const property = useProperty()
  const { can } = useSession()
  const navigate = useNavigate()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const status = params.get("status") ?? ""
  const method = params.get("method") ?? ""
  const from = params.get("from") ?? ""
  const to = params.get("to") ?? ""
  const start = Number(params.get("start") ?? 0) || 0
  const [booking, setBooking] = useState(params.get("booking") ?? "")
  const dBooking = useDebounced(booking.trim(), 400)
  const [manual, setManual] = useState(false)
  const closeManual = useEvent(() => setManual(false))

  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!("start" in patch)) next.delete("start")
    setParams(next, { replace: true })
  }

  // an open end stays open: the server filters on whichever bound is set (never the browser's "today")
  const badRange = Boolean(from && to && from > to)
  const q = useTexQuery<Txn[]>(
    "payments",
    "transactions",
    {
      property,
      status: status || undefined,
      method: method || undefined,
      booking: dBooking || undefined,
      date_from: from || undefined,
      date_to: to || undefined,
      start,
      limit: PAGE,
    },
    [property, status, method, dBooking, from, to, start],
    Boolean(property) && can("payment.view") && !badRange,
  )
  const filtered = Boolean(status || method || from || to || dBooking)
  const [verifying, setVerifying] = useState<string | null>(null)
  const reverifiable = (r: Txn) => can("payment.view") && r.txn_type === "Charge" && (r.status === "Pending" || r.status === "Failed") && (r.provider === "iyzico" || r.provider === "Sipay")
  const reverify = async (r: Txn) => {
    setVerifying(r.name)
    try {
      const out = await tex<{ status: string }>("payments", "reverify", { transaction: r.name }, { post: true })
      toast.success(t("payments.reverify.done", { status: t(statusKey(out.status)) }))
      q.reload()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setVerifying(null)
    }
  }

  return (
    <>
      <PageHeader
        title={t("payments.tx.title")}
        subtitle={t("payments.tx.subtitle")}
        crumbs={[{ label: t("core.nav.payments"), to: "/tex/payments" }, { label: t("payments.nav.transactions") }]}
        actions={
          <>
            {can("payment.link") && (
              <Button variant="secondary" icon={<Link2 className="size-4" aria-hidden />} onClick={() => navigate("/tex/payments/links?new=1")}>
                {t("payments.links.new")}
              </Button>
            )}
            {can("payment.refund") && (
              <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setManual(true)}>
                {t("payments.manual.open")}
              </Button>
            )}
          </>
        }
      />
      <PaymentsNav />
      {!can("payment.view") ? (
        <Card>
          <EmptyState title={t("core.error.permission")} description={t("payments.no_access")} />
        </Card>
      ) : (
        <>
          <Toolbar>
            <Field label={t("core.label.status")} className="w-[calc(50%-0.375rem)] sm:w-40">
              <Select
                value={status}
                onChange={(e) => set({ status: e.target.value })}
                options={[{ value: "", label: t("core.label.all") }, ...TXN_STATUSES.map((s) => ({ value: s, label: t(statusKey(s)) }))]}
              />
            </Field>
            <Field label={t("payments.tx.method")} className="w-[calc(50%-0.375rem)] sm:w-44">
              <Select
                value={method}
                onChange={(e) => set({ method: e.target.value })}
                options={[{ value: "", label: t("core.label.all") }, ...TXN_METHODS.map((m) => ({ value: m, label: t(methodKey(m)) }))]}
              />
            </Field>
            <Field label={t("core.label.from")} className="w-[calc(50%-0.375rem)] sm:w-40">
              <Input type="date" value={from} max={to || undefined} onChange={(e) => set({ from: e.target.value })} />
            </Field>
            <Field label={t("core.label.to")} className="w-[calc(50%-0.375rem)] sm:w-40" error={badRange ? t("payments.tx.bad_range") : undefined}>
              <Input type="date" value={to} min={from || undefined} onChange={(e) => set({ to: e.target.value })} />
            </Field>
            <Field label={t("payments.tx.booking")} className="w-full sm:w-48">
              <Input
                value={booking}
                onChange={(e) => {
                  setBooking(e.target.value)
                  set({ booking: e.target.value.trim() })
                }}
                placeholder="TEX-2026-00001"
                autoComplete="off"
              />
            </Field>
            {filtered && (
              <Button
                variant="ghost"
                onClick={() => {
                  setBooking("")
                  setParams({}, { replace: true })
                }}
              >
                {t("core.action.reset")}
              </Button>
            )}
          </Toolbar>
          <Card>
            {q.error ? (
              <ErrorState error={q.error} onRetry={q.reload} />
            ) : (
              <>
                <DataTable<Txn>
                  caption={t("payments.tx.caption")}
                  rows={badRange ? [] : q.data}
                  loading={q.loading}
                  rowKey={(r) => r.name}
                  onRowClick={(r) => navigate(`/tex/payments/transactions/${encodeURIComponent(r.name)}`)}
                  empty={
                    <EmptyState
                      title={filtered ? t("payments.tx.empty_filtered") : t("payments.tx.empty")}
                      description={filtered ? t("payments.tx.empty_filtered_hint") : t("payments.tx.empty_hint")}
                    />
                  }
                  columns={[
                    {
                      key: "created",
                      header: t("payments.tx.col.date"),
                      sortValue: (r) => r.created,
                      cell: (r) => (
                        <div className="min-w-0">
                          <p className="text-sm whitespace-nowrap">{dateTime(r.created)}</p>
                          <p className="font-mono text-xs text-zinc-500">{r.name}</p>
                          {/* phones: the status column is hidden to keep the amount visible */}
                          <p className="mt-1 sm:hidden">
                            <TxnStatusBadge status={r.status} />
                          </p>
                        </div>
                      ),
                    },
                    {
                      key: "type",
                      header: t("payments.tx.col.type"),
                      hideBelow: "md",
                      cell: (r) => <Badge tone={r.txn_type === "Refund" ? "danger" : "neutral"}>{t(typeKey(r.txn_type))}</Badge>,
                    },
                    { key: "method", header: t("payments.tx.method"), hideBelow: "sm", cell: (r) => <MethodLabel txn={r} /> },
                    {
                      key: "booking",
                      header: t("payments.tx.col.reference"),
                      hideBelow: "lg",
                      cell: (r) => (
                        <div className="text-xs">
                          <p className="font-mono">{r.booking || "—"}</p>
                          {r.payment_link && <p className="text-zinc-500">{t("payments.tx.via_link", { link: r.payment_link })}</p>}
                          {r.parent_transaction && <p className="text-zinc-500">{t("payments.tx.refund_of", { name: r.parent_transaction })}</p>}
                        </div>
                      ),
                    },
                    { key: "status", header: t("core.label.status"), hideBelow: "sm", cell: (r) => <TxnStatusBadge status={r.status} /> },
                    ...(q.data?.some(reverifiable)
                      ? [
                          {
                            key: "reverify",
                            header: <span className="sr-only">{t("payments.tx.col.actions")}</span>,
                            hideBelow: "sm" as const,
                            cell: (r: Txn) =>
                              reverifiable(r) ? (
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  icon={<RefreshCw className="size-3.5" aria-hidden />}
                                  loading={verifying === r.name}
                                  aria-label={`${t("payments.reverify.short")} · ${r.name}`}
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    void reverify(r)
                                  }}
                                  onKeyDown={(e) => e.stopPropagation()}
                                >
                                  {t("payments.reverify.short")}
                                </Button>
                              ) : null,
                          },
                        ]
                      : []),
                    {
                      key: "amount",
                      header: t("payments.tx.col.amount"),
                      align: "right",
                      sortValue: (r) => r.currency,
                      cell: (r) => (
                        <span className={r.txn_type === "Refund" ? "whitespace-nowrap text-rose-700" : "whitespace-nowrap"}>
                          {r.txn_type === "Refund" && <span aria-hidden>− </span>}
                          <Money amount={r.amount} currency={r.currency} />
                        </span>
                      ),
                    },
                  ]}
                />
                {(start > 0 || (q.data?.length ?? 0) >= PAGE) && (
                  <nav aria-label={t("payments.pager.label")} className="flex items-center justify-end gap-2 border-t border-zinc-100 px-4 py-2.5">
                    <Button variant="secondary" size="sm" icon={<ChevronLeft className="size-4" aria-hidden />} disabled={start === 0} onClick={() => set({ start: String(Math.max(0, start - PAGE)) })}>
                      {t("payments.pager.prev")}
                    </Button>
                    <Button variant="secondary" size="sm" disabled={(q.data?.length ?? 0) < PAGE} onClick={() => set({ start: String(start + PAGE) })}>
                      {t("payments.pager.next")}
                      <ChevronRight className="size-4" aria-hidden />
                    </Button>
                  </nav>
                )}
              </>
            )}
          </Card>
          <p className="mt-3 text-xs text-zinc-500">{t("payments.tx.card_note")}</p>
        </>
      )}
      {property && <ManualPaymentDialog open={manual} onClose={closeManual} property={property} onDone={(txn) => navigate(`/tex/payments/transactions/${encodeURIComponent(txn)}`)} />}
    </>
  )
}
