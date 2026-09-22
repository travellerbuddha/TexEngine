import { useEffect, useMemo, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Ban, Plus, RotateCw } from "lucide-react"
import { tex, useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { dateTime } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Button, Card, ConfirmDialog, DataTable, EmptyState, ErrorState, Field, Input, Money, PageHeader, Select, Toolbar, useToast } from "../../ui"
import { cn } from "../../../lib/utils"
import { bookingHref, LinkStatusBadge, PaymentsNav } from "./components/common"
import { isZero, linkStatusKey, useEvent } from "./lib"
import { CreateLinkDialog, LinkUrlDialog, ReissueDialog } from "./links/LinkDialogs"
import { LINK_STATUSES, type CreatedLink, type PayLink } from "./types"

interface Shown {
  url: string
  title: string
  emailedTo?: string | null
  emailFailed?: boolean
  reissued?: boolean
}

export default function Links() {
  const { t } = useTexT()
  const property = useProperty()
  const { can, property: prop } = useSession()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const status = params.get("status") ?? ""
  const [search, setSearch] = useState(params.get("q") ?? "")
  const q = useTexQuery<PayLink[]>("payments", "links", { property, status: status || undefined, limit: 200 }, [property, status], Boolean(property) && can("payment.view"))
  const [creating, setCreating] = useState(params.get("new") === "1")
  const [shown, setShown] = useState<Shown | null>(null)
  const [reissue, setReissue] = useState<PayLink | null>(null)
  const [cancel, setCancel] = useState<PayLink | null>(null)
  const closeCreate = useEvent(() => {
    setCreating(false)
    if (params.get("new")) {
      const next = new URLSearchParams(params)
      next.delete("new")
      setParams(next, { replace: true })
    }
  })
  const closeShown = useEvent(() => setShown(null))
  const closeReissue = useEvent(() => setReissue(null))
  const closeCancel = useEvent(() => setCancel(null))
  const canLink = can("payment.link")

  useEffect(() => {
    if (params.get("new") === "1" && canLink) setCreating(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.get("new")])

  const rows = useMemo(() => {
    const s = search.trim().toLowerCase()
    if (!s || !q.data) return q.data
    return q.data.filter((r) => [r.name, r.description, r.guest_name, r.guest_email, r.booking].some((v) => (v || "").toLowerCase().includes(s)))
  }, [q.data, search])

  const onCreated = (r: CreatedLink, emailTo: string | null) => {
    q.reload()
    if (r.url)
      setShown({
        url: r.url,
        title: t("payments.links.created_title", { name: r.link }),
        emailedTo: r.emailed === true ? emailTo : null,
        emailFailed: Boolean(emailTo) && r.emailed === false,
      })
    else if (r.replay) toast.info(t("payments.links.replay_hint"))
  }

  // URLs are bearer secrets shown once: the list offers a fresh one (reissue) instead of a stored copy
  const linkActions = (r: PayLink, className: string) => {
    const open = r.status === "Active" || r.status === "Partially Paid"
    if (!open && r.status !== "Draft") return null
    return (
      <div className={cn("flex flex-wrap gap-1", className)}>
        {open && (
          <Button variant="secondary" size="sm" icon={<RotateCw className="size-3.5" aria-hidden />} aria-label={`${t("payments.links.reissue")} · ${r.name}`} onClick={() => setReissue(r)}>
            {t("payments.links.reissue")}
          </Button>
        )}
        {(r.status === "Active" || r.status === "Draft") && (
          <Button variant="ghost" size="sm" icon={<Ban className="size-3.5" aria-hidden />} aria-label={`${t("payments.links.cancel")} · ${r.name}`} onClick={() => setCancel(r)}>
            {t("payments.links.cancel")}
          </Button>
        )}
      </div>
    )
  }

  return (
    <>
      <PageHeader
        title={t("payments.links.title")}
        subtitle={t("payments.links.subtitle")}
        crumbs={[{ label: t("core.nav.payments"), to: "/tex/payments" }, { label: t("payments.nav.links") }]}
        actions={
          canLink && (
            <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setCreating(true)}>
              {t("payments.links.new")}
            </Button>
          )
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
            <Field label={t("payments.links.search")} className="w-full sm:w-72">
              <Input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value)
                  const next = new URLSearchParams(params)
                  if (e.target.value) next.set("q", e.target.value)
                  else next.delete("q")
                  setParams(next, { replace: true })
                }}
                placeholder={t("payments.links.search_ph")}
              />
            </Field>
            <Field label={t("core.label.status")} className="w-full sm:w-48">
              <Select
                value={status}
                onChange={(e) => {
                  const next = new URLSearchParams(params)
                  if (e.target.value) next.set("status", e.target.value)
                  else next.delete("status")
                  setParams(next, { replace: true })
                }}
                options={[{ value: "", label: t("core.label.all") }, ...LINK_STATUSES.map((s) => ({ value: s, label: t(linkStatusKey(s)) }))]}
              />
            </Field>
          </Toolbar>
          <Card>
            {q.error ? (
              <ErrorState error={q.error} onRetry={q.reload} />
            ) : (
              <DataTable<PayLink>
                caption={t("payments.links.caption")}
                rows={rows}
                loading={q.loading}
                rowKey={(r) => r.name}
                empty={
                  <EmptyState
                    title={search || status ? t("payments.links.empty_filtered") : t("payments.links.empty")}
                    description={t("payments.links.empty_hint")}
                    action={
                      canLink && !search && !status ? (
                        <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setCreating(true)}>
                          {t("payments.links.new")}
                        </Button>
                      ) : undefined
                    }
                  />
                }
                columns={[
                  {
                    key: "desc",
                    header: t("payments.links.col.link"),
                    cell: (r) => (
                      <div className="max-w-[16rem] min-w-0 sm:max-w-72">
                        <p className="truncate text-sm font-medium text-zinc-900" title={r.description ?? undefined}>
                          {r.description || r.name}
                        </p>
                        <p className="truncate text-xs text-zinc-500">
                          <span className="font-mono">{r.name}</span>
                          {r.guest_name || r.guest_email ? ` · ${[r.guest_name, r.guest_email].filter(Boolean).join(" · ")}` : ""}
                        </p>
                        <p className="text-xs text-zinc-500 sm:hidden">{dateTime(r.creation)}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-2 sm:hidden">
                          <LinkStatusBadge status={r.status} />
                          <Money amount={r.amount} currency={r.currency} className="text-sm" />
                        </div>
                        {canLink && linkActions(r, "mt-1.5 sm:hidden")}
                      </div>
                    ),
                  },
                  {
                    key: "booking",
                    header: t("payments.detail.booking"),
                    hideBelow: "lg",
                    cell: (r) =>
                      r.booking ? (
                        <Link to={bookingHref(r.booking)} className="font-mono text-xs text-tex-700 hover:underline">
                          {r.booking}
                        </Link>
                      ) : (
                        <span className="text-xs text-zinc-500">{t("payments.links.no_booking")}</span>
                      ),
                  },
                  { key: "created", header: t("payments.links.col.created"), hideBelow: "md", sortValue: (r) => r.creation, cell: (r) => <span className="text-xs whitespace-nowrap">{dateTime(r.creation)}</span> },
                  { key: "expires", header: t("payments.links.col.expires"), hideBelow: "md", sortValue: (r) => r.expires_at ?? "", cell: (r) => <span className="text-xs whitespace-nowrap">{dateTime(r.expires_at)}</span> },
                  { key: "status", header: t("core.label.status"), hideBelow: "sm", cell: (r) => <LinkStatusBadge status={r.status} /> },
                  {
                    key: "amount",
                    header: t("payments.tx.col.amount"),
                    align: "right",
                    hideBelow: "sm",
                    cell: (r) => (
                      <div>
                        <Money amount={r.amount} currency={r.currency} />
                        {!isZero(r.paid_amount) && (
                          <p className="text-xs text-emerald-700">
                            {t("payments.links.paid")} <Money amount={r.paid_amount} currency={r.currency} />
                          </p>
                        )}
                      </div>
                    ),
                  },
                  ...(canLink
                    ? [
                        {
                          key: "actions",
                          header: <span className="sr-only">{t("payments.links.col.actions")}</span>,
                          align: "right" as const,
                          hideBelow: "sm" as const,
                          cell: (r: PayLink) => linkActions(r, "ml-auto max-w-56 justify-end"),
                        },
                      ]
                    : []),
                ]}
              />
            )}
          </Card>
          <p className="mt-3 text-xs text-zinc-500">{t("payments.links.footer_note")}</p>
        </>
      )}
      {property && (
        <CreateLinkDialog open={creating && canLink} onClose={closeCreate} property={property} defaultCurrency={prop?.currency || "EUR"} onCreated={onCreated} />
      )}
      <LinkUrlDialog open={Boolean(shown)} onClose={closeShown} url={shown?.url ?? ""} title={shown?.title ?? ""} emailedTo={shown?.emailedTo} emailFailed={shown?.emailFailed} reissued={shown?.reissued} />
      <ReissueDialog
        link={reissue}
        onClose={closeReissue}
        onDone={(url, l, email) => {
          q.reload()
          setShown({ url, title: t("payments.links.reissued_title", { name: l.name }), reissued: true, emailedTo: email.to, emailFailed: email.failed })
        }}
      />
      <ConfirmDialog
        open={Boolean(cancel)}
        onClose={closeCancel}
        tone="danger"
        requireReason
        title={t("payments.links.cancel_title")}
        body={cancel ? t("payments.links.cancel_body", { name: cancel.name }) : undefined}
        confirmLabel={t("payments.links.cancel_confirm")}
        onConfirm={async (reason) => {
          if (!cancel) return
          await tex("payments", "cancel_link", { name: cancel.name, reason }, { post: true })
          toast.success(t("payments.links.cancelled"))
          q.reload()
        }}
      />
    </>
  )
}
