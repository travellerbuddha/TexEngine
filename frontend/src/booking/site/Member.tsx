// Loyalty members on the booking site (C-04, owner 2026-10-03; ADR-078): sign in, or join the site's program, by a
// one-time link sent to the guest's e-mail; the session stays on this device for 30 days until the guest signs out.
// A signed-in member's searches are priced as a member's; anyone else sees the member price as "Member price".
import { BadgeCheck, LogOut, UserRound } from "lucide-react"
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { useI18n } from "../i18n"
import { ApiError, pub } from "../lib/api"
import { forgetMemberSession, keepMemberSession, memberSession, rememberMemberReturn, sessionTag } from "../lib/member"
import { refusalMessage } from "../lib/refusals"
import { isEmbedded } from "../lib/storage"
import type { MemberStatus } from "../types"
import { Button, Checkbox, Field, Input } from "../ui/controls"
import { Dialog } from "../ui/Dialog"
import { Alert } from "../ui/feedback"
import { useSite } from "./SiteContext"

export type MemberTab = "sign_in" | "join"

interface MemberCtx {
  /** the site has a loyalty program a guest may sign in to or join */
  available: boolean
  /** its programs' names, as one phrase ("Resort Club") */
  program: string
  /** the session token sent with searches, or null */
  session: string | null
  status: MemberStatus | null
  /** changes when the session or its membership changes: a search is priced again ("" signed out) */
  key: string
  openDialog: (tab?: MemberTab) => void
  /** a session the server opened (member_verify) for `expiresIn` seconds */
  signedIn: (session: string, expiresIn: number, status: MemberStatus) => void
  signOut: () => Promise<void>
  join: () => Promise<void>
}

const Ctx = createContext<MemberCtx | null>(null)

/** The member state, or null outside a site page (a payment link, a page without the provider). */
export function useMember(): MemberCtx | null {
  return useContext(Ctx)
}

export function MemberProvider({ children }: { children: ReactNode }) {
  const { site } = useSite()
  const programs = useMemo(() => site.membership?.programs ?? [], [site.membership])
  const available = programs.length > 0
  const [session, setSession] = useState<string | null>(() => (available ? memberSession(site.slug) : null))
  const [status, setStatus] = useState<MemberStatus | null>(null)
  const [dialog, setDialog] = useState<{ open: boolean; tab: MemberTab }>({ open: false, tab: "sign_in" })
  // a join on this page: the session's prices change
  const [joined, setJoined] = useState(0)
  const [params, setParams] = useSearchParams()

  // the session kept on this device: who it signs in, as the server says now (an ended one is forgotten)
  useEffect(() => {
    if (!session) return
    let live = true
    pub<MemberStatus>("member_status", { site: site.slug, member_session: session })
      .then((s) => live && setStatus(s))
      .catch((e: unknown) => {
        if (!live) return
        if (e instanceof ApiError && (e.code === "MEMBER_SESSION_ENDED" || e.code === "MEMBERSHIP_UNAVAILABLE")) {
          forgetMemberSession(site.slug)
          setSession(null)
          setStatus(null)
        }
      })
    return () => {
      live = false
    }
  }, [session, site.slug])

  // "?join=1": the link of the mail an address without a membership gets, and the member page's "join"; "?sign_in=1":
  // its "ask for a new link"
  useEffect(() => {
    const tab: MemberTab | null = params.get("join") === "1" ? "join" : params.get("sign_in") === "1" ? "sign_in" : null
    if (!available || !tab) return
    setDialog({ open: true, tab })
    const next = new URLSearchParams(params)
    next.delete("join")
    next.delete("sign_in")
    setParams(next, { replace: true })
  }, [available, params, setParams])

  const signedIn = useCallback(
    (token: string, expiresIn: number, s: MemberStatus) => {
      keepMemberSession(site.slug, token, expiresIn)
      setSession(token)
      setStatus(s)
    },
    [site.slug],
  )

  const signOut = useCallback(async () => {
    const token = session
    forgetMemberSession(site.slug)
    setSession(null)
    setStatus(null)
    if (token) await pub("member_sign_out", { site: site.slug, member_session: token }).catch(() => undefined)
  }, [session, site.slug])

  const join = useCallback(async () => {
    if (!session) return
    setStatus(await pub<MemberStatus>("member_join", { site: site.slug, member_session: session, accepted: 1 }))
    setJoined((n) => n + 1)
  }, [session, site.slug])

  const value = useMemo<MemberCtx>(
    () => ({
      available,
      program: programs.join(", "),
      session,
      status,
      key: session ? `${sessionTag(session)}.${joined}` : "",
      openDialog: (tab: MemberTab = "sign_in") => setDialog({ open: true, tab }),
      signedIn,
      signOut,
      join,
    }),
    [available, programs, session, status, joined, signedIn, signOut, join],
  )
  return (
    <Ctx.Provider value={value}>
      {children}
      {available && <MemberDialog open={dialog.open} tab={dialog.tab} onTab={(tab) => setDialog({ open: true, tab })} onClose={() => setDialog((d) => ({ ...d, open: false }))} />}
    </Ctx.Provider>
  )
}

/** The header's member control: "Members" to sign in or join; signed in, the guest's name, joining when they are no
 * member yet, and signing out. */
export function MemberButton() {
  const m = useMember()
  const { t } = useI18n()
  if (!m?.available || isEmbedded()) return null
  if (!m.session || !m.status)
    return (
      <Button variant="secondary" size="sm" onClick={() => m.openDialog("sign_in")}>
        <UserRound className="size-4" aria-hidden />
        {t("member.signIn")}
      </Button>
    )
  return (
    <div className="flex items-center gap-1.5">
      <span className="hidden items-center gap-1.5 text-sm font-medium sm:inline-flex" data-testid="member-hello">
        {m.status.member && <BadgeCheck className="size-4 text-ok" aria-hidden />}
        {t("member.hello", { name: m.status.first_name || m.status.email || "" })}
      </span>
      {!m.status.member && (
        <Button variant="secondary" size="sm" onClick={() => m.openDialog("join")}>
          {t("member.joinNow", { program: m.program })}
        </Button>
      )}
      <Button variant="ghost" size="sm" onClick={() => void m.signOut()} aria-label={t("member.signOut")}>
        <LogOut className="size-4" aria-hidden />
        <span className="hidden sm:inline">{t("member.signOut")}</span>
      </Button>
    </div>
  )
}

function MemberDialog({ open, tab, onTab, onClose }: { open: boolean; tab: MemberTab; onTab: (t: MemberTab) => void; onClose: () => void }) {
  const i18n = useI18n()
  const { t, lang } = i18n
  const { site } = useSite()
  const m = useMember()!
  const [email, setEmail] = useState("")
  const [first, setFirst] = useState("")
  const [last, setLast] = useState("")
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // signed in already: the dialog only joins (a member has nothing to do here)
  const signedIn = !!(m.session && m.status)

  useEffect(() => {
    if (open) {
      setSent(null)
      setError(null)
    }
  }, [open, tab])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if ((tab === "join" || signedIn) && !accepted) {
      setError(t("refusal.MEMBER_CONSENT_REQUIRED"))
      return
    }
    setBusy(true)
    try {
      if (signedIn) {
        await m.join()
        onClose()
        return
      }
      rememberMemberReturn(site.slug, window.location.search)
      await pub("member_link", {
        site: site.slug,
        email: email.trim(),
        purpose: tab,
        ...(tab === "join" ? { first_name: first.trim(), last_name: last.trim(), accepted: 1 } : {}),
        language: lang,
      })
      setSent(email.trim())
    } catch (err) {
      setError(refusalMessage(i18n, err instanceof ApiError ? err : null))
    } finally {
      setBusy(false)
    }
  }

  const consent = (
    <Checkbox label={t("member.accept", { program: m.program })} hint={t("member.acceptHint")} checked={accepted} onChange={setAccepted} required />
  )

  if (signedIn)
    return (
      <Dialog open={open} onClose={onClose} closeLabel={t("common.close")} title={t("member.joinTitle", { program: m.program })} width="28rem">
        {m.status?.member ? (
          <div className="space-y-4">
            <Alert tone="ok">{t("member.already", { program: m.program })}</Alert>
            <Button block onClick={onClose}>
              {t("common.done")}
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} noValidate className="space-y-4">
            <p className="text-sm text-soft">{t("member.joinSignedIn", { program: m.program, email: m.status?.email ?? "" })}</p>
            {consent}
            {error && <Alert tone="bad">{error}</Alert>}
            <Button type="submit" block busy={busy} disabled={busy}>
              {t("member.joinNow", { program: m.program })}
            </Button>
          </form>
        )}
      </Dialog>
    )

  return (
    <Dialog
      open={open}
      onClose={onClose}
      closeLabel={t("common.close")}
      title={tab === "join" ? t("member.joinTitle", { program: m.program }) : t("member.signInTitle")}
      width="28rem"
    >
      <div className="mb-4 flex gap-1 rounded-ui bg-sunken p-1" role="tablist" aria-label={t("member.signInTitle")}>
        {(["sign_in", "join"] as const).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            className={`flex-1 rounded-ui px-3 py-1.5 text-sm font-medium ${tab === k ? "bg-surface shadow-sm" : "text-soft"}`}
            onClick={() => onTab(k)}
          >
            {k === "join" ? t("member.joinTab") : t("member.signInTab")}
          </button>
        ))}
      </div>
      {sent ? (
        <div className="space-y-4">
          <Alert tone="ok" title={t("member.sentTitle")}>
            {tab === "join" ? t("member.joinSentBody", { email: sent }) : t("member.sentBody", { email: sent })}
          </Alert>
          <Button block onClick={onClose}>
            {t("common.done")}
          </Button>
        </div>
      ) : (
        <form onSubmit={submit} noValidate className="space-y-4">
          <p className="text-sm text-soft">{tab === "join" ? t("member.joinIntro", { program: m.program }) : t("member.intro", { program: m.program })}</p>
          <Field label={t("details.email")}>
            <Input type="email" inputMode="email" autoComplete="email" required spellCheck={false} value={email} onChange={(e) => setEmail(e.target.value.slice(0, 140))} />
          </Field>
          {tab === "join" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("details.firstName")}>
                <Input autoComplete="given-name" required value={first} onChange={(e) => setFirst(e.target.value.slice(0, 140))} />
              </Field>
              <Field label={t("details.lastName")}>
                <Input autoComplete="family-name" required value={last} onChange={(e) => setLast(e.target.value.slice(0, 140))} />
              </Field>
            </div>
          )}
          {tab === "join" && consent}
          {error && <Alert tone="bad">{error}</Alert>}
          <Button type="submit" block busy={busy} disabled={busy || !email.trim() || (tab === "join" && (!first.trim() || !last.trim()))}>
            {t("member.send")}
          </Button>
        </form>
      )}
    </Dialog>
  )
}
