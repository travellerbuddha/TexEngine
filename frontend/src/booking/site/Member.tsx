// Loyalty members on the booking site (C-04, owner 2026-10-03; ADR-078): sign in, or join the site's program, by a
// one-time link sent to the guest's e-mail; the session stays on this device for 30 days on a hotel's own host (in the
// tab on the platform's shared host) until the guest signs out. A signed-in member's searches are priced as a
// member's; anyone else sees the member price as "Member price". Every join is confirmed by the link, a signed-in
// guest's too.
import { BadgeCheck, LogOut, UserRound } from "lucide-react"
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { useI18n } from "../i18n"
import { ApiError, pub } from "../lib/api"
import { forgetMemberSession, memberSession, memberSessionKey, rememberMemberReturn, sessionTag } from "../lib/member"
import { refusalMessage } from "../lib/refusals"
import { isEmbedded, newKey } from "../lib/storage"
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
  /** the server could not say who the session signs in (a network error): it is kept, and can be signed out */
  unread: boolean
  /** changes when the session changes: a search is priced again ("" signed out) */
  key: string
  openDialog: (tab?: MemberTab) => void
  signOut: () => Promise<void>
  /** a signed-in guest who is no member asks to join: a link goes to their e-mail, which confirms it */
  join: () => Promise<void>
}

const Ctx = createContext<MemberCtx | null>(null)

/** The member state, or null outside a site page (a payment link, a page without the provider). */
export function useMember(): MemberCtx | null {
  return useContext(Ctx)
}

const ended = (e: unknown) => e instanceof ApiError && (e.code === "MEMBER_SESSION_ENDED" || e.code === "MEMBERSHIP_UNAVAILABLE")

export function MemberProvider({ children }: { children: ReactNode }) {
  const { site } = useSite()
  const { lang } = useI18n()
  const programs = useMemo(() => site.membership?.programs ?? [], [site.membership])
  const available = programs.length > 0
  const [session, setSession] = useState<string | null>(() => (available ? memberSession(site.slug) : null))
  const [status, setStatus] = useState<MemberStatus | null>(null)
  const [unread, setUnread] = useState(false)
  const [dialog, setDialog] = useState<{ open: boolean; tab: MemberTab }>({ open: false, tab: "sign_in" })
  const [params, setParams] = useSearchParams()

  const forget = useCallback(() => {
    forgetMemberSession(site.slug)
    setSession(null)
    setStatus(null)
  }, [site.slug])

  // the session kept here: who it signs in, as the server says now (an ended one is forgotten)
  useEffect(() => {
    setStatus(null)
    setUnread(false)
    if (!session) return
    let live = true
    pub<MemberStatus>("member_status", { site: site.slug, member_session: session })
      .then((s) => live && setStatus(s))
      .catch((e: unknown) => {
        if (!live) return
        if (ended(e)) forget()
        else setUnread(true)
      })
    return () => {
      live = false
    }
  }, [session, site.slug, forget])

  // another tab signed in or out on this device (a hotel's own host keeps the session on the device)
  useEffect(() => {
    if (!available) return
    const on = (e: StorageEvent) => {
      if (e.key === null || e.key === memberSessionKey(site.slug)) setSession(memberSession(site.slug))
    }
    window.addEventListener("storage", on)
    return () => window.removeEventListener("storage", on)
  }, [available, site.slug])

  // "?join=1": the link of the mail an address without a membership gets, and the member page's "join"; "?sign_in=1":
  // its "ask for a new link", and the widget's way to sign in (on the site, in a new tab)
  useEffect(() => {
    const tab: MemberTab | null = params.get("join") === "1" ? "join" : params.get("sign_in") === "1" ? "sign_in" : null
    if (!available || !tab) return
    setDialog({ open: true, tab })
    const next = new URLSearchParams(params)
    next.delete("join")
    next.delete("sign_in")
    setParams(next, { replace: true })
  }, [available, params, setParams])

  const signOut = useCallback(async () => {
    const token = session
    forget()
    if (token) await pub("member_sign_out", { site: site.slug, member_session: token }).catch(() => undefined)
  }, [session, site.slug, forget])

  const join = useCallback(async () => {
    if (!session) return
    try {
      await pub("member_join", { site: site.slug, member_session: session, accepted: 1, language: lang, idempotency_key: newKey("member-join") })
    } catch (e) {
      if (ended(e)) forget()
      throw e
    }
  }, [session, site.slug, lang, forget])

  const value = useMemo<MemberCtx>(
    () => ({
      available,
      program: programs.join(", "),
      session,
      status,
      unread,
      key: session ? sessionTag(session) : "",
      openDialog: (tab: MemberTab = "sign_in") => setDialog({ open: true, tab }),
      signOut,
      join,
    }),
    [available, programs, session, status, unread, signOut, join],
  )
  return (
    <Ctx.Provider value={value}>
      {children}
      {available && <MemberDialog open={dialog.open} tab={dialog.tab} onTab={(tab) => setDialog({ open: true, tab })} onClose={() => setDialog((d) => ({ ...d, open: false }))} />}
    </Ctx.Provider>
  )
}

/** The header's member control: "Member sign-in" to sign in or join; signed in, the guest's name, joining when they
 * are no member yet, and signing out. Nothing while a kept session is being read (never "sign in" for a guest who is). */
export function MemberButton() {
  const m = useMember()
  const { t } = useI18n()
  if (!m?.available || isEmbedded()) return null
  if (!m.session)
    return (
      <Button variant="secondary" size="sm" onClick={() => m.openDialog("sign_in")}>
        <UserRound className="size-4" aria-hidden />
        {t("member.signIn")}
      </Button>
    )
  if (!m.status)
    // the status could not be read (a network error): the guest can still sign out; nothing while it is read
    return m.unread ? (
      <Button variant="ghost" size="sm" onClick={() => void m.signOut()} aria-label={t("member.signOut")}>
        <LogOut className="size-4" aria-hidden />
        <span className="hidden sm:inline">{t("member.signOut")}</span>
      </Button>
    ) : null
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

const TABS: readonly MemberTab[] = ["sign_in", "join"]

function MemberDialog({ open, tab, onTab, onClose }: { open: boolean; tab: MemberTab; onTab: (t: MemberTab) => void; onClose: () => void }) {
  const i18n = useI18n()
  const { t, lang } = i18n
  const { site } = useSite()
  const m = useMember()!
  const base = useId()
  const tabRefs = useRef<Record<MemberTab, HTMLButtonElement | null>>({ sign_in: null, join: null })
  const [email, setEmail] = useState("")
  const [first, setFirst] = useState("")
  const [last, setLast] = useState("")
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // signed in already: the dialog only asks for the join link (a member has nothing to do here)
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
      rememberMemberReturn(site.slug, window.location.search)
      if (signedIn) {
        await m.join()
        setSent(m.status?.email ?? "")
        return
      }
      await pub("member_link", {
        site: site.slug,
        email: email.trim(),
        purpose: tab,
        ...(tab === "join" ? { first_name: first.trim(), last_name: last.trim(), accepted: 1 } : {}),
        language: lang,
        idempotency_key: newKey("member-link"),
      })
      setSent(email.trim())
    } catch (err) {
      setError(refusalMessage(i18n, err instanceof ApiError ? err : null))
    } finally {
      setBusy(false)
    }
  }

  // arrow keys move between the two tabs (the WAI-ARIA tabs pattern)
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return
    e.preventDefault()
    const i = TABS.indexOf(tab)
    const next = e.key === "Home" ? TABS[0] : e.key === "End" ? TABS[TABS.length - 1] : TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length]
    onTab(next)
    tabRefs.current[next]?.focus()
  }

  const consent = <Checkbox label={t("member.accept", { program: m.program })} hint={t("member.acceptHint")} checked={accepted} onChange={setAccepted} required />
  const sentNote = (
    <div className="space-y-4">
      <Alert tone="ok" title={t("member.sentTitle")}>
        {tab === "join" || signedIn ? t("member.joinSentBody", { email: sent ?? "" }) : t("member.sentBody", { email: sent ?? "" })}
      </Alert>
      <Button block onClick={onClose}>
        {t("common.done")}
      </Button>
    </div>
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
        ) : sent !== null ? (
          sentNote
        ) : (
          <form onSubmit={submit} noValidate className="space-y-4">
            <p className="text-sm text-soft">{t("member.joinSignedIn", { program: m.program, email: m.status?.email ?? "" })}</p>
            {consent}
            {error && <Alert tone="bad">{error}</Alert>}
            <Button type="submit" block busy={busy} disabled={busy}>
              {t("member.send")}
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
        {TABS.map((k) => (
          <button
            key={k}
            ref={(el) => {
              tabRefs.current[k] = el
            }}
            id={`${base}-tab-${k}`}
            type="button"
            role="tab"
            aria-selected={tab === k}
            aria-controls={`${base}-panel`}
            tabIndex={tab === k ? 0 : -1}
            className={`flex-1 rounded-ui px-3 py-1.5 text-sm font-medium ${tab === k ? "bg-surface shadow-sm" : "text-soft"}`}
            onClick={() => onTab(k)}
            onKeyDown={onTabKey}
          >
            {k === "join" ? t("member.joinTab") : t("member.signInTab")}
          </button>
        ))}
      </div>
      <div id={`${base}-panel`} role="tabpanel" aria-labelledby={`${base}-tab-${tab}`}>
        {sent !== null ? (
          sentNote
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
      </div>
    </Dialog>
  )
}
