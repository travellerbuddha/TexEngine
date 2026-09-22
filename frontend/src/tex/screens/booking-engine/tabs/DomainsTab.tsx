import { useState } from "react"
import { CheckCircle2, Plus, ShieldCheck, Trash2 } from "lucide-react"
import { tex, TexApiError } from "../../../lib/api"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Notice, useToast } from "../../../ui"
import { CodeBlock } from "../../settings/components/common"
import { DOMAIN, normaliseDomain, type SiteDomain } from "../site"
import type { TabProps } from "./common"

interface VerifyResult {
  domain: string
  verified: boolean
  record: string
  expected: string
  found: string[]
}

export function DomainsTab({ site, set, err, isNew, dirty, reload }: TabProps) {
  const { t } = useTexT()
  const toast = useToast()
  const [draft, setDraft] = useState("")
  const [draftErr, setDraftErr] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, VerifyResult | { error: string }>>({})
  const domains = site.domains

  const add = () => {
    const d = normaliseDomain(draft)
    if (!DOMAIN.test(d)) return setDraftErr(t("be.err.domain"))
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
      if (r.verified) {
        toast.success(t("be.domains.verified_toast", { domain: d.domain }))
        if (!d.verified) reload()
      }
    } catch (e) {
      setResults((m) => ({ ...m, [d.domain]: { error: (e as TexApiError).message } }))
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
          {domains.length === 0 ? (
            <p className="text-sm text-zinc-500">{t("be.domains.empty")}</p>
          ) : (
            <ul className="space-y-3" aria-label={t("be.domains.title")}>
              {domains.map((d, i) => {
                const saved = !!d.verification_token
                const record = `_tex-verify.${d.domain}`
                const res = results[d.domain]
                return (
                  <li key={`${d.domain}-${i}`} className="rounded-lg border border-zinc-200 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-medium break-all text-zinc-900">{d.domain}</span>
                        {d.verified ? (
                          <Badge tone="success">
                            <CheckCircle2 className="size-3" aria-hidden />
                            {t("be.domains.verified")}
                          </Badge>
                        ) : (
                          <Badge tone="warning">{saved ? t("be.domains.unverified") : t("be.domains.unsaved")}</Badge>
                        )}
                        {d.is_primary ? <Badge tone="brand">{t("be.domains.primary")}</Badge> : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {!d.is_primary && (
                          <Button variant="ghost" size="sm" onClick={() => set({ domains: domains.map((x, j) => ({ ...x, is_primary: j === i ? 1 : 0 })) })}>
                            {t("be.domains.make_primary")}
                          </Button>
                        )}
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={<ShieldCheck className="size-3.5" aria-hidden />}
                          loading={busy === d.domain}
                          disabled={!saved || dirty || isNew}
                          title={!saved || dirty ? t("be.domains.save_first") : undefined}
                          onClick={() => verify(d)}
                        >
                          {d.verified ? t("be.domains.recheck") : t("be.domains.verify")}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 className="size-3.5" aria-hidden />}
                          aria-label={t("be.domains.remove", { domain: d.domain })}
                          onClick={() => {
                            const next = domains.filter((_, j) => j !== i)
                            if (d.is_primary && next.length && !next.some((x) => x.is_primary)) next[0] = { ...next[0], is_primary: 1 }
                            set({ domains: next })
                          }}
                        >
                          <span className="hidden sm:inline">{t("core.action.delete")}</span>
                        </Button>
                      </div>
                    </div>
                    {saved ? (
                      !d.verified && (
                        <div className="mt-3 space-y-3 rounded-lg bg-zinc-50 p-3">
                          <p className="text-sm text-zinc-700">{t("be.domains.instructions")}</p>
                          <div className="grid gap-3 md:grid-cols-[auto_1fr_1fr]">
                            <div className="space-y-1.5">
                              <p className="text-xs font-medium text-zinc-600">{t("be.domains.type")}</p>
                              <pre className="rounded-lg border border-zinc-200 bg-white px-3 py-2 font-mono text-xs">TXT</pre>
                            </div>
                            <CodeBlock label={t("be.domains.host")} value={record} />
                            <CodeBlock label={t("be.domains.value")} value={d.verification_token ?? ""} />
                          </div>
                          <p className="text-xs text-zinc-500">{t("be.domains.propagation")}</p>
                        </div>
                      )
                    ) : (
                      <p className="mt-2 text-xs text-zinc-500">{t("be.domains.save_for_record")}</p>
                    )}
                    {res && (
                      <div className="mt-3" aria-live="polite">
                        {"error" in res ? (
                          <Notice tone="danger" title={t("be.domains.check_failed")}>
                            {res.error}
                          </Notice>
                        ) : res.verified ? (
                          <Notice tone="success">{t("be.domains.ok", { record: res.record })}</Notice>
                        ) : (
                          <Notice tone="warning" title={t("be.domains.not_found_title")}>
                            <p>{t("be.domains.not_found", { record: res.record })}</p>
                            {res.found.length > 0 && (
                              <p className="mt-1 text-xs">
                                {t("be.domains.found")} <span className="font-mono break-all">{res.found.join(", ")}</span>
                              </p>
                            )}
                          </Notice>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          <form
            className="flex flex-wrap items-start gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              add()
            }}
          >
            <Field label={t("be.domains.add_label")} error={draftErr ?? undefined} hint={t("be.domains.add_hint")} className="min-w-0 flex-1">
              <Input
                inputMode="url"
                placeholder="booking.hotel.com"
                spellCheck={false}
                autoCapitalize="none"
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
        </CardBody>
      </Card>
    </div>
  )
}
