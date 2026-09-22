import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { ArrowLeftRight, Landmark, RefreshCw, RotateCcw, SquareArrowDownRight } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { dateTime } from "../../lib/format"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  DataTable,
  DescriptionList,
  EmptyState,
  ErrorState,
  InlineError,
  Money,
  Notice,
  PageHeader,
  Skeleton,
  useToast,
} from "../../ui"
import { bookingHref, CardLabel, PaymentsNav, TxnStatusBadge } from "./components/common"
import { AllocateDialog, canAllocate, canConfirmTransfer, canRefund, canReverify, canTransfer, ConfirmTransferDialog, RefundDialog, TransferDialog } from "./detail/Actions"
import { allocKey, methodKey, typeKey, useEvent } from "./lib"
import type { Allocation, Txn, TxnDetail } from "./types"

type Action = "refund" | "allocate" | "transfer" | "bank" | null

export default function TransactionDetail() {
  const { name = "" } = useParams()
  const { t } = useTexT()
  const { can } = useSession()
  const toast = useToast()
  const q = useTexQuery<TxnDetail>("payments", "transaction", { name }, [name])
  const [action, setAction] = useState<Action>(null)
  const close = useEvent(() => setAction(null))
  const reverify = useTexMutation<{ transaction: string }, { status: string; replay?: boolean }>("payments", "reverify")
  const d = q.data
  const crumbs = [
    { label: t("core.nav.payments"), to: "/tex/payments" },
    { label: t("payments.nav.transactions"), to: "/tex/payments" },
    { label: name },
  ]

  if (q.error)
    return (
      <>
        <PageHeader title={t("payments.detail.title", { name })} crumbs={crumbs} />
        <PaymentsNav />
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      </>
    )

  const finance = d ? can("payment.refund", d.property) : false
  const charge = d?.txn_type === "Charge"

  const doReverify = async () => {
    if (!d) return
    try {
      const r = await reverify.run({ transaction: d.name })
      toast.success(t("payments.reverify.done", { status: t(`payments.status.${r.status.toLowerCase()}`) }))
      q.reload()
    } catch {
      /* inline */
    }
  }

  return (
    <>
      <PageHeader
        title={t("payments.detail.title", { name })}
        crumbs={crumbs}
        meta={
          d && (
            <>
              <TxnStatusBadge status={d.status} />
              <Badge tone={d.txn_type === "Refund" ? "danger" : "neutral"}>{t(typeKey(d.txn_type))}</Badge>
              <Badge tone="neutral">{t(methodKey(d.method))}</Badge>
              {d.provider === "Mock" && <Badge tone="warning">{t("payments.sandbox")}</Badge>}
            </>
          )
        }
        actions={
          d && (
            <>
              {can("payment.view", d.property) && canReverify(d) && (
                <Button variant="secondary" icon={<RefreshCw className="size-4" aria-hidden />} loading={reverify.pending} onClick={doReverify}>
                  {t("payments.reverify.button")}
                </Button>
              )}
              {finance && canConfirmTransfer(d) && (
                <Button icon={<Landmark className="size-4" aria-hidden />} onClick={() => setAction("bank")}>
                  {t("payments.bank.button")}
                </Button>
              )}
              {finance && canAllocate(d) && (
                <Button variant="secondary" icon={<SquareArrowDownRight className="size-4" aria-hidden />} onClick={() => setAction("allocate")}>
                  {t("payments.allocate.button")}
                </Button>
              )}
              {finance && canTransfer(d) && (
                <Button variant="secondary" icon={<ArrowLeftRight className="size-4" aria-hidden />} onClick={() => setAction("transfer")}>
                  {t("payments.transfer.button")}
                </Button>
              )}
              {finance && canRefund(d) && (
                <Button variant="danger" icon={<RotateCcw className="size-4" aria-hidden />} onClick={() => setAction("refund")}>
                  {t("payments.refund.button")}
                </Button>
              )}
            </>
          )
        }
      />
      <PaymentsNav />
      {!d ? (
        <Card className="p-4">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="mt-4 h-24 w-full" />
        </Card>
      ) : (
        <div className="space-y-5">
          <InlineError error={reverify.error} />
          {d.status === "Pending" && d.provider === "Bank Transfer" && <Notice tone="warning">{t("payments.detail.pending_bank")}</Notice>}
          {d.status === "Pending" && (d.provider === "iyzico" || d.provider === "Sipay") && <Notice tone="warning">{t("payments.detail.pending_gateway")}</Notice>}
          {d.status === "Failed" && canReverify(d) && <Notice tone="info">{t("payments.detail.failed_gateway")}</Notice>}
          {d.status === "Failed" && (d.error_message || d.error_code) && (
            <Notice tone="danger" title={t("payments.detail.failed")}>
              {[d.error_code, d.error_message].filter(Boolean).join(" · ")}
            </Notice>
          )}
          {charge && d.status === "Succeeded" && (d.provider === "Manual" || d.provider === "Loyalty") && finance && (
            <Notice tone="info">{t("payments.detail.manual_refund_note")}</Notice>
          )}

          <section aria-label={t("payments.detail.amounts")} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Card className="p-4">
              <p className="text-xs font-medium tracking-wide text-zinc-500 uppercase">{t("payments.amount")}</p>
              <p className="mt-1 text-2xl font-semibold tracking-tight text-zinc-950">
                <Money amount={d.amount} currency={d.currency} />
              </p>
            </Card>
            {charge && (
              <>
                <Card className="p-4">
                  <p className="text-xs font-medium tracking-wide text-zinc-500 uppercase">{t("payments.detail.refundable")}</p>
                  <p className="mt-1 text-2xl font-semibold tracking-tight text-zinc-950">
                    <Money amount={d.refundable} currency={d.currency} />
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">{t("payments.detail.refundable_hint")}</p>
                </Card>
                <Card className="p-4">
                  <p className="text-xs font-medium tracking-wide text-zinc-500 uppercase">{t("payments.detail.unallocated")}</p>
                  <p className="mt-1 text-2xl font-semibold tracking-tight text-zinc-950">
                    <Money amount={d.unallocated} currency={d.currency} />
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">{t("payments.detail.unallocated_hint")}</p>
                </Card>
              </>
            )}
          </section>

          <Card>
            <CardHeader title={t("payments.detail.details")} />
            <CardBody>
              <DescriptionList
                cols={3}
                items={[
                  { label: t("payments.detail.method"), value: t(methodKey(d.method)) },
                  { label: t("payments.detail.card"), value: d.card_brand || d.card_last4 ? <CardLabel brand={d.card_brand} last4={d.card_last4} /> : "—" },
                  { label: t("payments.detail.provider"), value: d.provider || "—" },
                  { label: t("payments.detail.provider_ref"), value: d.provider_ref ? <span className="font-mono text-xs break-all">{d.provider_ref}</span> : "—" },
                  {
                    label: t("payments.detail.booking"),
                    value: d.booking ? (
                      <Link className="font-mono text-tex-700 hover:underline" to={bookingHref(d.booking)}>
                        {d.booking}
                      </Link>
                    ) : (
                      "—"
                    ),
                  },
                  {
                    label: t("payments.detail.link"),
                    value: d.payment_link ? (
                      <Link className="font-mono text-tex-700 hover:underline" to={`/tex/payments/links?q=${encodeURIComponent(d.payment_link)}`}>
                        {d.payment_link}
                      </Link>
                    ) : (
                      "—"
                    ),
                  },
                  {
                    label: t("payments.detail.parent"),
                    value: d.parent_transaction ? (
                      <Link className="font-mono text-tex-700 hover:underline" to={`/tex/payments/transactions/${encodeURIComponent(d.parent_transaction)}`}>
                        {d.parent_transaction}
                      </Link>
                    ) : (
                      "—"
                    ),
                  },
                  { label: t("payments.detail.created"), value: dateTime(d.created) },
                  { label: t("payments.detail.completed"), value: dateTime(d.completed_at) },
                  { label: t("payments.detail.actor"), value: d.actor === "Guest" ? t("payments.actor.guest") : d.actor || "—" },
                  { label: t("payments.detail.reason"), value: d.reason || "—" },
                  { label: t("payments.detail.hotel"), value: d.property },
                ]}
              />
            </CardBody>
          </Card>

          {charge && (
            <div className="grid items-start gap-5 xl:grid-cols-2">
              <Card className="min-w-0">
                <CardHeader title={t("payments.detail.allocations")} description={t("payments.detail.allocations_hint")} />
                <DataTable<Allocation>
                  caption={t("payments.detail.allocations")}
                  rows={d.allocations}
                  rowKey={(a) => a.name}
                  dense
                  empty={<EmptyState title={t("payments.detail.no_allocations")} />}
                  columns={[
                    { key: "date", header: t("payments.tx.col.date"), cell: (a) => <span className="text-xs whitespace-nowrap">{dateTime(a.creation)}</span> },
                    { key: "type", header: t("payments.tx.col.type"), cell: (a) => <Badge tone={a.allocation_type === "Allocate" ? "success" : "warning"}>{t(allocKey(a.allocation_type))}</Badge> },
                    { key: "booking", header: t("payments.detail.booking"), cell: (a) => <span className="font-mono text-xs">{a.booking || "—"}</span> },
                    { key: "reason", header: t("payments.detail.reason"), hideBelow: "md", cell: (a) => <span className="text-xs text-zinc-600">{a.reason || "—"}</span> },
                    {
                      key: "amount",
                      header: t("payments.tx.col.amount"),
                      align: "right",
                      cell: (a) => (
                        <span className={a.allocation_type === "Allocate" ? "whitespace-nowrap" : "whitespace-nowrap text-rose-700"}>
                          {a.allocation_type !== "Allocate" && <span aria-hidden>− </span>}
                          <Money amount={a.amount} currency={a.currency} />
                        </span>
                      ),
                    },
                  ]}
                />
              </Card>
              <Card className="min-w-0">
                <CardHeader title={t("payments.detail.refunds")} />
                <DataTable<Txn>
                  caption={t("payments.detail.refunds")}
                  rows={d.refunds}
                  rowKey={(r) => r.name}
                  dense
                  empty={<EmptyState title={t("payments.detail.no_refunds")} />}
                  columns={[
                    {
                      key: "name",
                      header: t("payments.detail.refund"),
                      cell: (r) => (
                        <div>
                          <Link className="font-mono text-xs text-tex-700 hover:underline" to={`/tex/payments/transactions/${encodeURIComponent(r.name)}`}>
                            {r.name}
                          </Link>
                          <p className="text-xs whitespace-nowrap text-zinc-500">{dateTime(r.created)}</p>
                        </div>
                      ),
                    },
                    { key: "status", header: t("core.label.status"), cell: (r) => <TxnStatusBadge status={r.status} /> },
                    { key: "reason", header: t("payments.detail.reason"), hideBelow: "md", cell: (r) => <span className="text-xs text-zinc-600">{r.reason || "—"}</span> },
                    { key: "amount", header: t("payments.tx.col.amount"), align: "right", cell: (r) => <Money amount={r.amount} currency={r.currency} /> },
                  ]}
                />
              </Card>
            </div>
          )}
          <p className="text-xs text-zinc-500">{t("payments.tx.card_note")}</p>

          <RefundDialog open={action === "refund"} onClose={close} txn={d} onDone={q.reload} />
          <AllocateDialog open={action === "allocate"} onClose={close} txn={d} onDone={q.reload} />
          <TransferDialog open={action === "transfer"} onClose={close} txn={d} onDone={q.reload} />
          <ConfirmTransferDialog open={action === "bank"} onClose={close} txn={d} onDone={q.reload} />
        </div>
      )}
    </>
  )
}
