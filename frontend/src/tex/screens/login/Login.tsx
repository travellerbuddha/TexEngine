import { useEffect, useState } from "react"
import { login } from "../../../lib/api"
import { asset } from "../../../lib/asset"
import { getSiteInfo } from "../../../lib/siteInfo"
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

const FALLBACK: EntryInfo = { product: "TEX Engine", brand_name: "TEX Engine", source_url: "" }

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
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [demoMode, setDemoMode] = useState(false)
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

  async function submit(u = usr, p = pwd) {
    setBusy(true)
    setError(null)
    try {
      await login(u, p)
      sessionStorage.removeItem("kamra_session_ended")
      onSuccess()
    } catch {
      setError(t("core.login.failed"))
    } finally {
      setBusy(false)
    }
  }

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
                  value={usr}
                  onChange={(e) => setUsr(e.target.value)}
                  placeholder={t("core.login.user_ph")}
                />
              </Field>
              <Field label={t("core.login.password")}>
                <Input type="password" autoComplete="current-password" value={pwd} onChange={(e) => setPwd(e.target.value)} />
              </Field>
              {error && (
                <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                  {error}
                </p>
              )}
              <Button type="submit" className="w-full justify-center" loading={busy} disabled={busy || !usr || !pwd}>
                {busy ? t("core.login.busy") : t("core.login.submit")}
              </Button>
            </form>
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
