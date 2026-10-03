// The page a member's e-mail link opens (/member#token=…, C-04, ADR-078): the link is spent once for a session kept
// on this device for 30 days, then the guest is back on the site's search, priced as a member.
import { BadgeCheck, MailWarning } from "lucide-react"
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useI18n } from "../i18n"
import { ApiError, pub } from "../lib/api"
import { keepMemberSession, memberReturn, memberSession, takeMemberLinkToken } from "../lib/member"
import { siteRoute, sitePath, useSiteSlug } from "../lib/mount"
import { refusalMessage } from "../lib/refusals"
import { Shell } from "../site/Layout"
import { MemberProvider } from "../site/Member"
import { SiteProvider, useSite, useSiteData } from "../site/SiteContext"
import type { MemberStatus } from "../types"
import { EmptyState, Spinner } from "../ui/feedback"
import { SiteError } from "./SiteError"

interface Verified {
  session: string
  expires_in: number
  status: MemberStatus
}

// a link is spent by its first use: one request per token, however often the page renders (StrictMode runs effects
// twice in development)
const verifying = new Map<string, Promise<Verified>>()
let linkToken: string | null | undefined

function verify(site: string, token: string): Promise<Verified> {
  let p = verifying.get(token)
  if (!p) {
    p = pub<Verified>("member_verify", { site, token })
    verifying.set(token, p)
  }
  return p
}

type State = { kind: "checking" } | { kind: "refused"; error: ApiError | null } | { kind: "none" }

function MemberLink() {
  const { site } = useSite()
  const i18n = useI18n()
  const { t } = i18n
  const navigate = useNavigate()
  const [state, setState] = useState<State>({ kind: "checking" })
  const program = (site.membership?.programs ?? []).join(", ")

  useEffect(() => {
    if (linkToken === undefined) linkToken = takeMemberLinkToken()
    const token = linkToken
    if (!token) {
      // no link (opened again, or typed): a session kept here goes on to the search
      if (memberSession(site.slug)) navigate(siteRoute(site.slug), { replace: true })
      else setState({ kind: "none" })
      return
    }
    let live = true
    verify(site.slug, token)
      .then((v) => {
        linkToken = undefined
        if (!live) return
        keepMemberSession(site.slug, v.session, v.expires_in)
        navigate(siteRoute(site.slug, memberReturn(site.slug) ?? ""), { replace: true })
      })
      .catch((e: unknown) => {
        linkToken = undefined
        if (live) setState({ kind: "refused", error: e instanceof ApiError ? e : null })
      })
    return () => {
      live = false
    }
  }, [site.slug, navigate])

  useEffect(() => {
    document.title = [t("member.signInTitle"), site.name].join(" · ")
  }, [site.name, t])

  if (state.kind === "checking")
    return (
      <div className="grid min-h-40 place-items-center py-10">
        <Spinner label={t("member.checking")} />
      </div>
    )
  const code = state.kind === "refused" ? state.error?.code : null
  const join = code === "NOT_A_MEMBER"
  return (
    <EmptyState
      icon={join ? <BadgeCheck className="size-8" aria-hidden /> : <MailWarning className="size-8" aria-hidden />}
      title={state.kind === "none" ? t("member.noLink") : join ? t("member.notMemberTitle") : t("member.linkTitle")}
      actions={
        code === "MEMBERSHIP_UNAVAILABLE" ? (
          <a href={sitePath(site.slug)} className="bk-btn bk-btn-primary">
            {t("member.toSearch")}
          </a>
        ) : (
          <>
            <a href={sitePath(site.slug, join ? "?join=1" : "?sign_in=1")} className="bk-btn bk-btn-primary">
              {join ? t("member.joinNow", { program }) : t("member.askAgain")}
            </a>
            <a href={sitePath(site.slug)} className="bk-btn bk-btn-secondary">
              {t("member.toSearch")}
            </a>
          </>
        )
      }
    >
      {state.kind === "none" ? t("member.noLinkBody") : refusalMessage(i18n, state.error)}
    </EmptyState>
  )
}

export default function MemberPage() {
  const slug = useSiteSlug()
  const { site, error, retry } = useSiteData(slug)
  if (error) return <SiteError error={error} onRetry={retry} />
  if (!site) return <Spinner className="p-10" />
  return (
    <SiteProvider site={site}>
      <MemberProvider>
        <Shell home={sitePath(site.slug)}>
          <div className="mx-auto max-w-xl px-4 py-10 sm:px-6">
            <h1 className="sr-only">{site.membership?.programs?.join(", ") || site.name}</h1>
            <MemberLink />
          </div>
        </Shell>
      </MemberProvider>
    </SiteProvider>
  )
}
