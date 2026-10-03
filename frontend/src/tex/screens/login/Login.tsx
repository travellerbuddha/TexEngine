import { useEffect, useRef, useState } from "react"
import { login, loginOtp, sameOrigin, type LoginResult } from "../../../lib/api"
import { asset } from "../../../lib/asset"
import { getSiteInfo } from "../../../lib/siteInfo"
import { servedBrand } from "../../../lib/source"
import { tex } from "../../lib/api"
import { setTexLang, TEX_LANGS, useTexI18nReady, useTexT, type TexLang } from "../../i18n"
import { SourceNotice } from "../../shell/SourceNotice"
import { Button, Card, CardBody, Field, Input, Notice, Spinner } from "../../ui"

/** What the public sign-in page shows (kamra.tex.api.session.entry, ADR-060). */
interface EntryInfo {
  product: string
  brand_name: string
  source_url: string
}

// the served page carries the brand and the source offer (kamra/www/kamra.py): shown even when
// session.entry is rate limited or down
const FALLBACK: EntryInfo = { product: "TEX Engine", brand_name: servedBrand() || "TEX Engine", source_url: "" }

// Frappe's own sign-in page: password reset, and single sign-on / LDAP where the site has them
const FORGOT = "/login#forgot"
const OTHER_SIGN_IN = "/login?redirect-to=%2Fkamra%2Ftex"
// a signed-in user without Desk access: Frappe's portal (kamra.tex.entry.PORTAL)
const PORTAL = "/me"

/** A two-factor sign-in waiting for its code (Frappe keeps the password for `tmp_id`). */
interface OtpStep {
  tmp_id: string
  verification: NonNullable<LoginResult["verification"]>
}

// Kamra's public playground only (kamra_demo_mode): one-click sign-in per role
const DEMO_ACCOUNTS = [
  { label: "core.login.demo.admin", usr: "admin@kamra.local", pwd: "KamraAdmin1!" },
  { label: "core.login.demo.gm", usr: "gm@kamra.local", pwd: "KamraGM1!" },
  { label: "core.login.demo.front_desk", usr: "frontdesk@kamra.local", pwd: "KamraDesk1!" },
  { label: "core.login.demo.revenue", usr: "revenue@kamra.local", pwd: "KamraRev1!" },
  { label: "core.login.demo.finance", usr: "finance@kamra.local", pwd: "KamraFin1!" },
  { label: "core.login.demo.housekeeping", usr: "hk@kamra.local", pwd: "KamraHK1!" },
]

/** Sign-in (G-60): the brand from TEX Settings, the six TEX languages, the source offer. */
export default function Login(props: { onSuccess: () => void }) {
  const ready = useTexI18nReady()
  if (!ready)
    return (
      <div className="tex-root flex min-h-[100dvh] items-center justify-center bg-zinc-50">
        <Spinner />
      </div>
    )
  return <LoginForm {...props} />
}

function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const { t, lang } = useTexT()
  const [info, setInfo] = useState<EntryInfo>(FALLBACK)
  const [usr, setUsr] = useState("")
  const [pwd, setPwd] = useState("")
  // what went wrong; `fields`: the fields hold it (wrong credentials or code), not the account
  const [error, setError] = useState<{ text: string; fields: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const [demoMode, setDemoMode] = useState(false)
  const [otp, setOtp] = useState<OtpStep | null>(null)
  const [code, setCode] = useState("")
  const codeRef = useRef<HTMLInputElement>(null)
  const sessionEnded = sessionStorage.getItem("kamra_session_ended") === "1"

  useEffect(() => {
    let alive = true
    tex<EntryInfo>("session", "entry")
      .then((i) => alive && setInfo(i))
      .catch(() => undefined) // offline or rate limited: the product name still shows
    getSiteInfo().then((s) => alive && setDemoMode(Boolean(s.demo_mode)))
    return () => {
      alive = false
    }
  }, [])

  const brand = info.brand_name || info.product
  useEffect(() => {
    document.title = `${t("core.login.title")} · ${brand}`
  }, [t, brand])

  useEffect(() => {
    if (otp) codeRef.current?.focus()
  }, [otp])

  /** Frappe answers 200 without a session too (frappe/auth.py): only "Logged In" signs in to the
   * admin app (M1). A two-factor account first gives its code, an expired password is renewed on
   * Frappe's page (on this site only: a `redirect_to` answer, or the link Frappe v16.36.1 mails), a
   * website user goes to the portal; anything else is told. */
  function settle(r: LoginResult) {
    if (r.message === "Logged In") {
      sessionStorage.removeItem("kamra_session_ended")
      onSuccess()
      return
    }
    if (r.message === "No App") {
      // signed in, but without Desk access: the admin app is not theirs ("/" sends them there too)
      window.location.assign(PORTAL)
      return
    }
    if (r.tmp_id && r.verification) {
      if (r.verification.token_delivery === false) {
        setError({ text: t("core.login.otp_not_sent"), fields: false })
        return
      }
      setCode("")
      setOtp({ tmp_id: r.tmp_id, verification: r.verification })
      return
    }
    if (r.message === "Password Reset") {
      const to = sameOrigin(r.redirect_to)
      if (to) {
        window.location.assign(to)
        return
      }
      setError({ text: t("core.login.password_expired"), fields: false })
      return
    }
    setError({ text: t("core.login.incomplete"), fields: false })
  }

  async function submit(u = usr, p = pwd) {
    setBusy(true)
    setError(null)
    try {
      settle(await login(u, p))
    } catch {
      setError({ text: t("core.login.failed"), fields: true })
    } finally {
      setBusy(false)
    }
  }

  async function verify() {
    if (!otp) return
    setBusy(true)
    setError(null)
    try {
      settle(await loginOtp(code.trim(), otp.tmp_id))
    } catch {
      setError({ text: t("core.login.otp_failed"), fields: true })
      setCode("")
      codeRef.current?.focus()
    } finally {
      setBusy(false)
    }
  }

  // an authenticator app's first sign-in is answered as "Email" too: Frappe mails how to set it up
  const method = otp?.verification.method
  const otpPrompt = method === "SMS" ? t("core.login.otp_sms") : method === "Email" ? t("core.login.otp_email") : t("core.login.otp_app")
  // the message is tied to the fields (L7): described by it, and invalid when they hold the fault
  const errorId = "tex-login-error"
  const invalid = error ? { "aria-describedby": errorId, ...(error.fields ? { "aria-invalid": true } : {}) } : {}

  return (
    // TEX languages are all left-to-right, whatever an earlier Kamra session chose
    <div dir="ltr" className="tex-root flex min-h-[100dvh] flex-col bg-zinc-50 px-4 text-zinc-900">
      <div className="fixed inset-x-0 top-0 h-1 bg-tex-600" aria-hidden />
      <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10">
        <div className="mb-6 flex flex-col items-center gap-3 text-center">
          <img src={asset("tex-mark.svg")} alt="" className="size-12" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-950">{brand}</h1>
            <p className="mt-1 text-sm text-zinc-600">{t("core.login.tagline")}</p>
          </div>
        </div>

        {sessionEnded && (
          <div className="mb-4">
            <Notice tone="warning">{t("core.login.session_ended")}</Notice>
          </div>
        )}

        <Card>
          <CardBody>
            {otp ? (
              <form
                className="space-y-4"
                aria-label={t("core.login.otp_title")}
                onSubmit={(e) => {
                  e.preventDefault()
                  void verify()
                }}
              >
                <h2 className="text-base font-semibold text-zinc-900">{t("core.login.otp_title")}</h2>
                <p className="text-sm text-zinc-600">{otpPrompt}</p>
                <Field label={t("core.login.otp_label")}>
                  <Input
                    ref={codeRef}
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]*"
                    maxLength={10}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    {...invalid}
                  />
                </Field>
                {error && (
                  <p id={errorId} role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                    {error.text}
                  </p>
                )}
                <Button type="submit" className="w-full justify-center" loading={busy} disabled={busy || code.trim().length < 4}>
                  {t("core.login.otp_submit")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  className="w-full justify-center"
                  disabled={busy}
                  onClick={() => {
                    setOtp(null)
                    setError(null)
                  }}
                >
                  {t("core.login.back")}
                </Button>
              </form>
            ) : (
              <form
                className="space-y-4"
                aria-label={t("core.login.title")}
                onSubmit={(e) => {
                  e.preventDefault()
                  void submit()
                }}
              >
                <h2 className="text-base font-semibold text-zinc-900">{t("core.login.title")}</h2>
                <Field label={t("core.login.user")}>
                  <Input
                    type="text"
                    autoComplete="username"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    // the page is only this form: start in it
                    autoFocus
                    value={usr}
                    onChange={(e) => setUsr(e.target.value)}
                    placeholder={t("core.login.user_ph")}
                    {...invalid}
                  />
                </Field>
                <Field label={t("core.login.password")}>
                  <Input type="password" autoComplete="current-password" value={pwd} onChange={(e) => setPwd(e.target.value)} {...invalid} />
                </Field>
                {error && (
                  <p id={errorId} role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                    {error.text}
                  </p>
                )}
                <Button type="submit" className="w-full justify-center" loading={busy} disabled={busy || !usr || !pwd}>
                  {busy ? t("core.login.busy") : t("core.login.submit")}
                </Button>
              </form>
            )}
            <div className="mt-4 flex flex-wrap justify-between gap-2 text-xs">
              <a href={FORGOT} className="text-tex-700 underline underline-offset-2 hover:text-tex-800">
                {t("core.login.forgot")}
              </a>
              <a href={OTHER_SIGN_IN} className="text-tex-700 underline underline-offset-2 hover:text-tex-800">
                {t("core.login.other_options")}
              </a>
            </div>
          </CardBody>
        </Card>

        {demoMode && (
          <div className="mt-4 rounded-xl border border-dashed border-zinc-300 p-4">
            <Notice tone="warning">{t("core.login.demo.warning")}</Notice>
            <p className="my-2 text-center text-xs text-zinc-600">{t("core.login.demo.title")}</p>
            <div className="grid grid-cols-2 gap-2">
              {DEMO_ACCOUNTS.map((a) => (
                <Button key={a.usr} variant="secondary" size="sm" disabled={busy} onClick={() => void submit(a.usr, a.pwd)}>
                  {t(a.label)}
                </Button>
              ))}
            </div>
          </div>
        )}

        <div className="mt-6 flex justify-center">
          <label className="flex items-center gap-2 text-xs text-zinc-600">
            <span>{t("core.shell.language")}</span>
            <select
              id="tex-login-lang"
              value={lang}
              onChange={(e) => void setTexLang(e.target.value as TexLang)}
              className="h-8 rounded-lg border border-zinc-300 bg-white px-2 text-xs text-zinc-800 focus:border-tex-500 focus:outline-none"
            >
              {TEX_LANGS.map((l) => (
                <option key={l.code} value={l.code} lang={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </main>
      <footer className="pb-5 text-center">
        <SourceNotice sourceUrl={info.source_url} className="text-xs" />
      </footer>
    </div>
  )
}
