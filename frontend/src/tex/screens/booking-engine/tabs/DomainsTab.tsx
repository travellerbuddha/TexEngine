import { useId, useState } from "react"
import { AlertTriangle, CheckCircle2, Plus, ShieldCheck, Trash2 } from "lucide-react"
import { tex, TexApiError } from "../../../lib/api"
import { dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Notice, useToast } from "../../../ui"
import { CodeBlock } from "../../settings/components/common"
import { domainError, normaliseDomain, UNVERIFY_AFTER, type Site, type SiteDomain } from "../site"
import type { TabProps } from "./common"

/** admin.verify_domain → kamra.tex.services.sites.verify_domain. `verified` is the
 * domain's stored state (a missing record un-verifies it only after UNVERIFY_AFTER daily
 * checks); `present` is whether THIS lookup found the TXT record carrying the token. */
interface VerifyResult {
  domain: string
  verified: boolean
  present?: boolean
  record: string
  expected: string
  found: string[]
}
type Result = VerifyResult | { error: string }

/** Did this check find the record? Decided from the lookup, never from the domain state. */
function recordPresent(res: VerifyResult) {
  return res.present ?? res.found.includes(res.expected)
}

/** The host a custom domain's CNAME points at: this platform (where staff sign in). A DNS
 * record never carries a port, so the host name alone. */
function platformHost() {
  return window.location.hostname
}

/** One DNS record to create, each part with a copy button. */
function DnsRecord({ type, label, name, value, valueLabel }: { type: string; label: string; name: string; value: string; valueLabel: string }) {
  const { t } = useTexT()
  return (
    <div role="group" aria-label={label} className="grid gap-3 sm:grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-1.5">
        <p className="text-xs font-medium text-zinc-600">{t("be.domains.type")}</p>
        <pre className="rounded-lg border border-zinc-200 bg-white px-3 py-2 font-mono text-xs">{type}</pre>
      </div>
      <CodeBlock label={t("be.domains.host")} value={name} />
      <CodeBlock label={valueLabel} value={value} />
    </div>
  )
}

/** CNAME to the platform, TXT with the ownership token, then Verify. */
function DnsSteps({ d }: { d: SiteDomain }) {
  const { t } = useTexT()
  return (
    <ol className="space-y-4">
      <li className="space-y-2">
        <p className="text-sm text-zinc-800">
          <span className="font-semibold">1.</span> {t("be.domains.step_cname", { domain: d.domain })}
        </p>
        <DnsRecord type="CNAME" label={t("be.domains.cname_record")} name={d.domain} value={platformHost()} valueLabel={t("be.domains.target")} />
        <p className="text-xs text-zinc-500">{t("be.domains.step_cname_hint")}</p>
      </li>
      <li className="space-y-2">
        <p className="text-sm text-zinc-800">
          <span className="font-semibold">2.</span> {t("be.domains.step_txt")}
        </p>
        <DnsRecord type="TXT" label={t("be.domains.txt_record")} name={`_tex-verify.${d.domain}`} value={d.verification_token ?? ""} valueLabel={t("be.domains.value")} />
      </li>
      <li className="space-y-1">
        <p className="text-sm text-zinc-800">
          <span className="font-semibold">3.</span> {t("be.domains.step_verify")}
        </p>
        <p className="text-xs text-zinc-500">{t("be.domains.propagation")}</p>
      </li>
    </ol>
  )
}

/** Verification state as the server's DNS check left it (read-only). */
function DomainState({ d }: { d: SiteDomain }) {
  const { t } = useTexT()
  const failures = Number(d.check_failures ?? 0) || 0
  return (
    <>
      <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-medium text-zinc-500">{t("be.domains.status")}</dt>
          <dd className="text-zinc-900">
            {d.verified ? (d.verified_at ? t("be.domains.verified_since", { when: dateTime(d.verified_at) }) : t("be.domains.verified")) : t("be.domains.unverified")}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-zinc-500">{t("be.domains.last_check")}</dt>
          <dd className="text-zinc-900">{d.last_checked_at ? dateTime(d.last_checked_at) : t("be.domains.never_checked")}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-zinc-500">{t("be.domains.failures_label")}</dt>
          <dd className={failures > 0 ? "inline-flex items-center gap-1 font-medium text-amber-800 tabular-nums" : "text-zinc-900 tabular-nums"}>
            {failures > 0 && <AlertTriangle className="size-3.5" aria-hidden />}
            {t("be.domains.failures_value", { count: failures, limit: UNVERIFY_AFTER })}
          </dd>
        </div>
      </dl>
      {failures > 0 && (
        <div className="mt-3">
          {d.verified ? (
            <Notice tone="warning" title={t("be.domains.failures_title")}>
              {t("be.domains.failures_warning", { count: failures, limit: UNVERIFY_AFTER })}
            </Notice>
          ) : failures >= UNVERIFY_AFTER ? (
            <Notice tone="warning" title={t("be.domains.lapsed_title")}>
              {t("be.domains.lapsed", { count: failures })}
            </Notice>
          ) : null}
        </div>
      )}
    </>
  )
}

function VerifyOutcome({ res }: { res: Result }) {
  const { t } = useTexT()
  if ("error" in res)
    return (
      <Notice tone="danger" title={t("be.domains.check_failed")}>
        {res.error}
      </Notice>
    )
  if (recordPresent(res)) return <Notice tone="success">{t("be.domains.ok", { record: res.record })}</Notice>
  const values = (
    <>
      <p className="mt-1 text-xs">
        {t("be.domains.expected")} <span className="font-mono break-all">{res.expected}</span>
      </p>
      {res.found.length > 0 && (
        <p className="mt-1 text-xs">
          {t("be.domains.found")} <span className="font-mono break-all">{res.found.join(", ")}</span>
        </p>
      )}
    </>
  )
  // record missing on this check, but the domain stays verified until the daily checks lapse it
  if (res.verified)
    return (
      <Notice tone="warning" title={t("be.domains.failures_title")}>
        <p>{t("be.domains.still_verified_missing", { record: res.record, limit: UNVERIFY_AFTER })}</p>
        {values}
      </Notice>
    )
  return (
    <Notice tone="warning" title={t("be.domains.not_found_title")}>
      <p>{t("be.domains.not_found", { record: res.record })}</p>
      {values}
    </Notice>
  )
}

/** Which address guest links use, as kamra.tex.services.sites.primary_host picks it: none
 * while the site is switched off (its domains are not served), else the verified primary,
 * else the first verified domain, else the platform's /book/<slug>. */
function LinksSummary({ site }: { site: Site }) {
  const { t } = useTexT()
  const verified = site.domains.filter((d) => d.verified)
  const primary = site.domains.find((d) => d.is_primary)
  const used = verified.find((d) => d.is_primary) ?? verified[0]
  const texUrl = `${window.location.origin}/book/${site.site_slug || "…"}`
  return (
    <div className="space-y-2 rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-sm break-words text-zinc-700">
      <p>
        <span className="font-semibold text-zinc-900">{t("be.domains.primary")}:</span> {t("be.domains.primary_hint")}
      </p>
      {!site.enabled ? (
        <p className="font-medium text-amber-800">{t("be.domains.links_disabled")}</p>
      ) : (
        <p>{used ? t("be.domains.links_use_host", { url: `https://${used.domain}` }) : t("be.domains.links_use_tex", { url: texUrl })}</p>
      )}
      {primary && !primary.verified && <p className="font-medium text-amber-800">{t("be.domains.primary_unverified", { domain: primary.domain })}</p>}
    </div>
  )
}

function DomainRow({
  d,
  index,
  site,
  set,
  canVerify,
  busy,
  result,
  onVerify,
}: {
  d: SiteDomain
  index: number
  site: Site
  set: TabProps["set"]
  canVerify: boolean
  busy: boolean
  result?: Result
  onVerify: (d: SiteDomain) => void
}) {
  const { t } = useTexT()
  const nameId = useId()
  const domains = site.domains
  const saved = !!d.verification_token
  const invalid = domainError(d.domain)
  return (
    <li className="rounded-lg border border-zinc-200 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span id={nameId} className="font-mono text-sm font-medium break-all text-zinc-900">
            {d.domain}
          </span>
          {d.verified ? (
            <Badge tone="success">
              <CheckCircle2 className="size-3" aria-hidden />
              {t("be.domains.verified")}
            </Badge>
          ) : (
            <Badge tone={invalid ? "danger" : "warning"}>{invalid ? t("be.domains.invalid") : saved ? t("be.domains.unverified") : t("be.domains.unsaved")}</Badge>
          )}
          {d.is_primary ? <Badge tone="brand">{t("be.domains.primary")}</Badge> : null}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {!d.is_primary && !invalid && (
            <Button variant="ghost" size="sm" aria-describedby={nameId} onClick={() => set({ domains: domains.map((x, j) => ({ ...x, is_primary: j === index ? 1 : 0 })) })}>
              {t("be.domains.make_primary")}
            </Button>
          )}
          {!invalid && (
            <Button
              variant="secondary"
              size="sm"
              icon={<ShieldCheck className="size-3.5" aria-hidden />}
              loading={busy}
              disabled={!saved || !canVerify}
              title={!saved || !canVerify ? t("be.domains.save_first") : undefined}
              aria-describedby={nameId}
              onClick={() => onVerify(d)}
            >
              {d.verified ? t("be.domains.recheck") : t("be.domains.verify")}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 className="size-3.5" aria-hidden />}
            aria-label={t("be.domains.remove", { domain: d.domain })}
            onClick={() => {
              const next = domains.filter((_, j) => j !== index)
              if (d.is_primary && next.length && !next.some((x) => x.is_primary)) next[0] = { ...next[0], is_primary: 1 }
              set({ domains: next })
            }}
          >
            <span className="hidden sm:inline">{t("core.action.delete")}</span>
          </Button>
        </div>
      </div>

      {invalid ? (
        <div className="mt-3">
          <Notice tone="danger">{t("be.domains.row_invalid")}</Notice>
        </div>
      ) : saved ? (
        <>
          <DomainState d={d} />
          {d.verified ? (
            <details className="mt-3 rounded-lg bg-zinc-50 p-3">
              <summary className="cursor-pointer text-sm font-medium text-zinc-800">{t("be.domains.records")}</summary>
              <div className="mt-3 space-y-3">
                <p className="text-xs text-zinc-600">{t("be.domains.keep_records")}</p>
                <DnsSteps d={d} />
              </div>
            </details>
          ) : (
            <div className="mt-3 space-y-3 rounded-lg bg-zinc-50 p-3">
              <p className="text-sm font-medium text-zinc-900">{t("be.domains.steps_title")}</p>
              <DnsSteps d={d} />
            </div>
          )}
        </>
      ) : (
        <p className="mt-2 text-xs text-zinc-500">{t("be.domains.save_for_record")}</p>
      )}

      {result && (
        <div className="mt-3" aria-live="polite">
          <VerifyOutcome res={result} />
        </div>
      )}
    </li>
  )
}

export function DomainsTab({ site, set, err, isNew, dirty, reload }: TabProps) {
  const { t } = useTexT()
  const toast = useToast()
  const [draft, setDraft] = useState("")
  const [draftErr, setDraftErr] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, Result>>({})
  const domains = site.domains

  const add = () => {
    const problem = domainError(draft)
    if (problem) return setDraftErr(t(problem))
    const d = normaliseDomain(draft)
    if (domains.some((x) => normaliseDomain(x.domain) === d)) return setDraftErr(t("be.domains.duplicate"))
    set({ domains: [...domains, { domain: d, is_primary: domains.length === 0 ? 1 : 0, verified: 0 }] })
    setDraft("")
    setDraftErr(null)
  }

  const verify = async (d: SiteDomain) => {
    if (!site.name) return
    setBusy(d.domain)
    try {
      const r = await tex<VerifyResult>("admin", "verify_domain", { site: site.name, domain: d.domain }, { post: true })
      setResults((m) => ({ ...m, [d.domain]: r }))
      if (recordPresent(r) && !d.verified) toast.success(t("be.domains.verified_toast", { domain: d.domain }))
      // the check stored its outcome (last check, failures, verified since): show it
      reload()
    } catch (e) {
      setResults((m) => ({ ...m, [d.domain]: { error: e instanceof TexApiError ? e.message : t("be.domains.check_failed") } }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("be.domains.title")} description={t("be.domains.hint")} />
        <CardBody className="space-y-4">
          {err("domains") && <Notice tone="danger">{err("domains")}</Notice>}
          {dirty && domains.some((d) => d.verification_token && !d.verified) && <p className="text-xs font-medium text-amber-800">{t("be.domains.save_first")}</p>}
          {domains.length > 0 && <LinksSummary site={site} />}
          {domains.length === 0 ? (
            <p className="text-sm text-zinc-500">{t("be.domains.empty")}</p>
          ) : (
            <ul className="space-y-3" aria-label={t("be.domains.title")}>
              {domains.map((d, i) => (
                <DomainRow
                  key={`${d.domain}-${i}`}
                  d={d}
                  index={i}
                  site={site}
                  set={set}
                  canVerify={!dirty && !isNew}
                  busy={busy === d.domain}
                  result={results[d.domain]}
                  onVerify={(x) => void verify(x)}
                />
              ))}
            </ul>
          )}
          <form
            className="flex flex-wrap items-start gap-2"
            noValidate
            onSubmit={(e) => {
              e.preventDefault()
              add()
            }}
          >
            <Field label={t("be.domains.add_label")} error={draftErr ?? undefined} hint={t("be.domains.add_hint")} className="min-w-0 flex-1 basis-60">
              <Input
                inputMode="url"
                placeholder="book.yourhotel.com"
                spellCheck={false}
                autoCapitalize="none"
                autoComplete="off"
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value)
                  setDraftErr(null)
                }}
              />
            </Field>
            <Button type="submit" variant="secondary" icon={<Plus className="size-4" aria-hidden />} className="sm:mt-7" disabled={!draft.trim()}>
              {t("be.domains.add")}
            </Button>
          </form>
          <p className="text-xs text-zinc-500">{t("be.domains.security_note")}</p>
          <p className="text-xs text-zinc-500">{t("be.domains.tls_note")}</p>
        </CardBody>
      </Card>
    </div>
  )
}
