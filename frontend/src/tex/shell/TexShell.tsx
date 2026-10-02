import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { Link, useHref, useLocation, useNavigate } from "react-router-dom"
import { Building2, ChevronDown, ExternalLink, LogOut, Menu, Moon, Rocket, Search, Sun, X } from "lucide-react"
import { cn } from "../../lib/utils"
import { useAuth } from "../../lib/auth"
import { getTheme, setTheme } from "../../lib/theme"
import { toFullPath } from "../../lib/routing"
import { areaEntry, areaHome, childActive, childPath, childVisible, inArea, NAV, NAV_GROUPS, type NavChild, type NavItem } from "./nav"
import { SourceNotice } from "./SourceNotice"
import { tex, type TexApiError } from "../lib/api"
import { UnsavedChangesProvider, useConfirmLeave } from "../lib/unsaved"
import { date as fmtDate } from "../lib/format"
import { useSession } from "../lib/session"
import { setTexLang, TEX_LANGS, useTexT, type TexLang } from "../i18n"
import { Badge, Button, Dialog, Field, IconButton, InlineError, Kbd, Notice, Textarea, useToast } from "../ui"

interface VisibleNavItem extends NavItem {
  /** Sub-sections this user may open here (R-35, G-64). */
  sub: NavChild[]
}

function useVisibleNav(): VisibleNavItem[] {
  const { can } = useSession()
  return useMemo(
    () =>
      NAV.filter((n) => n.anyOf.some((c) => can(c))).map((n) => {
        const sub = (n.children ?? []).filter((c) => childVisible(c, (cap) => can(cap)))
        return { ...n, to: areaEntry(n, sub), sub }
      }),
    [can],
  )
}

/** Pages that show one record of the selected hotel: switching hotel goes back to their list,
 * so the header never names one hotel while the page shows another's contract or rule. */
const HOTEL_RECORDS: [RegExp, string][] = [
  [/^\/tex\/rates\/contracts\/.+/, "/tex/rates"],
  [/^\/tex\/rates\/policies\/([^/]+)\/(?!new$)[^/]+$/, "/tex/rates/policies/$1"],
]

function HotelSwitcher() {
  const { boot, property, setProperty } = useSession()
  const { t } = useTexT()
  const toast = useToast()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const confirmLeave = useConfirmLeave()
  const [flash, setFlash] = useState(false)
  useEffect(() => {
    if (!flash) return
    const h = window.setTimeout(() => setFlash(false), 1600)
    return () => window.clearTimeout(h)
  }, [flash])
  if (boot.properties.length <= 1)
    return (
      <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-zinc-800">
        <Building2 className="size-4 shrink-0 text-zinc-500" aria-hidden />
        <span className="truncate">{property?.property_name ?? t("core.shell.no_hotel")}</span>
      </div>
    )
  const change = (name: string) => {
    // a hotel switch leaves the screen's unsaved edits behind: ask first (the select stays as it was)
    if (!confirmLeave()) return
    const next = boot.properties.find((p) => p.name === name)
    setProperty(name)
    setFlash(true)
    toast.info(t("core.shell.hotel_switched", { hotel: next?.property_name ?? name }))
    for (const [re, to] of HOTEL_RECORDS) if (re.test(pathname)) navigate(pathname.replace(re, to))
  }
  return (
    <label className="flex min-w-0 flex-1 items-center gap-2">
      <Building2 className="size-4 shrink-0 text-zinc-500" aria-hidden />
      {/* the hotel the whole screen works on, named in words (not only by the select's value) */}
      <span className="hidden text-xs font-medium tracking-wide text-zinc-500 uppercase sm:inline">{t("core.shell.hotel")}</span>
      <span className="sr-only sm:hidden">{t("core.shell.hotel")}</span>
      <select
        value={property?.name ?? ""}
        onChange={(e) => change(e.target.value)}
        className={cn(
          "h-9 w-full max-w-[18rem] min-w-0 truncate rounded-lg border border-zinc-300 bg-white pr-8 pl-2 text-sm font-semibold text-zinc-900 focus:border-tex-500 focus:ring-2 focus:ring-tex-500/30 focus:outline-none",
          flash && "tex-flash",
        )}
      >
        {boot.properties.map((p) => (
          <option key={p.name} value={p.name}>
            {p.property_name}
            {p.city ? ` · ${p.city}` : ""}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Whether the selected hotel is sold through TEX (ADR-052 review): "TEX live", or onboarding. */
function TexModeBadge() {
  const { property } = useSession()
  const { t } = useTexT()
  if (!property?.tex_mode) return null
  return property.tex_mode === "live" ? (
    <Badge tone="brand" className="hidden shrink-0 sm:inline-flex" title={t("core.shell.tex_live_hint")}>
      {t("core.shell.tex_live")}
    </Badge>
  ) : (
    <Badge tone="warning" className="hidden shrink-0 sm:inline-flex" title={t("core.shell.tex_onboarding_hint")}>
      {t("core.shell.tex_onboarding")}
    </Badge>
  )
}

/** An onboarding hotel is still sold at the legacy Desk: say so, and let an administrator
 * (settings.admin) set it live in TEX, with a reason (audited on the server). */
function OnboardingBanner() {
  const { property, can, reload } = useSession()
  const { t } = useTexT()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TexApiError>()
  if (property?.tex_mode !== "onboarding") return null
  const admin = can("settings.admin")
  const submit = async () => {
    setBusy(true)
    setError(undefined)
    try {
      await tex("admin", "set_hotel_live", { property: property.name, live: 1, reason: reason.trim() }, { post: true })
      toast.success(t("core.shell.go_live_done", { hotel: property.property_name }))
      setOpen(false)
      await reload()
    } catch (e) {
      setError(e as TexApiError)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="mx-auto w-full max-w-[1400px] px-3 pt-4 sm:px-6">
      <Notice tone="warning" title={t("core.shell.onboarding_title", { hotel: property.property_name })}>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <p>{t("core.shell.onboarding_body")}</p>
          {admin && (
            <Button size="sm" icon={<Rocket className="size-4" aria-hidden />} onClick={() => {
              setReason("")
              setError(undefined)
              setOpen(true)
            }}>
              {t("core.shell.go_live")}
            </Button>
          )}
        </div>
      </Notice>
      <Dialog
        open={open}
        onClose={busy ? () => undefined : () => setOpen(false)}
        size="sm"
        title={t("core.shell.go_live_title", { hotel: property.property_name })}
        description={t("core.shell.go_live_body")}
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)} disabled={busy}>
              {t("core.action.cancel")}
            </Button>
            <Button loading={busy} disabled={!reason.trim()} onClick={() => void submit()}>
              {t("core.shell.go_live_confirm")}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label={t("core.shell.go_live_reason")} hint={t("core.hint.reason_audited")}>
            <Textarea id="go-live-reason" value={reason} onChange={(e) => setReason(e.target.value)} data-autofocus />
          </Field>
          <InlineError error={error} />
        </div>
      </Dialog>
    </div>
  )
}

const navLinkCls = (active: boolean) =>
  cn(
    "flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm font-medium transition-colors",
    active ? "bg-tex-50 text-tex-800" : "text-zinc-700 hover:bg-zinc-100 hover:text-zinc-950",
  )

/** An area's own link: current on the area's own pages (`areaHome`), so Contracts is not current
 * on a promotion's page although both live under /tex/rates. */
function AreaLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const { t } = useTexT()
  const { pathname } = useLocation()
  const current = areaHome(item, pathname)
  return (
    <Link to={item.to} onClick={onNavigate} aria-current={current ? "page" : undefined} className={navLinkCls(current)}>
      <item.icon className="size-4 shrink-0" aria-hidden />
      <span className="truncate">{t(item.label)}</span>
    </Link>
  )
}

/** An area with its sub-sections: open while the user is in the area, or when toggled. */
function NavArea({ item, open, onToggle, onNavigate }: { item: VisibleNavItem; open: boolean; onToggle: () => void; onNavigate?: () => void }) {
  const { t } = useTexT()
  const { pathname } = useLocation()
  const listId = `tex-nav-sub-${item.id}`
  return (
    <li>
      <div className="flex items-center gap-0.5">
        <AreaLink item={item} onNavigate={onNavigate} />
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          // the list exists only while open: point at it only then
          aria-controls={open ? listId : undefined}
          aria-label={t("core.nav.sections", { area: t(item.label) })}
          className="grid size-8 shrink-0 place-items-center rounded-lg text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900"
        >
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} aria-hidden />
        </button>
      </div>
      {open && (
        <ul id={listId} className="mt-0.5 mb-1.5 ml-[1.05rem] space-y-0.5 border-l border-zinc-200 pl-2">
          {item.sub.map((c) => {
            if (c.unavailable)
              return (
                <li key={c.id}>
                  <span aria-disabled="true" className="block rounded-md px-2 py-1 text-[13px] text-zinc-500" data-testid={`tex-nav-${c.id}`}>
                    <span className="block truncate">{t(c.label)}</span>
                    <span className="block text-[11px] leading-tight">{t("core.nav.not_available")}</span>
                  </span>
                </li>
              )
            const active = childActive(c, item, pathname)
            return (
              <li key={c.id}>
                <Link
                  to={c.to}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "block truncate rounded-md px-2 py-1 text-[13px] transition-colors",
                    active ? "bg-tex-50 font-medium text-tex-800" : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950",
                  )}
                >
                  {t(c.label)}
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </li>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const items = useVisibleNav()
  const { boot } = useSession()
  const { t } = useTexT()
  const { pathname } = useLocation()
  const base = useHref("/").replace(/\/$/, "")
  const areasAt = (path: string) => items.filter((n) => inArea(n, n.sub, path)).map((n) => n.id).join(",")
  const current = areasAt(pathname)
  // areas opened or closed by hand, kept while the user stays in the areas they were in then and
  // forgotten when they move to another. A toggle made while a navigation is still loading (the
  // router shows the old location until the new screen's code is in) belongs to where the user is
  // going: it was lost when that navigation landed (G-64 review, found by the e2e).
  const [toggled, setToggled] = useState<{ at: string; open: Record<string, boolean> }>({ at: current, open: {} })
  useEffect(() => setToggled((s) => (s.at === current ? s : { at: current, open: {} })), [current])
  const byHand = toggled.at === current ? toggled.open : {}
  const toggle = (n: VisibleNavItem) => {
    const live = window.location.pathname
    const going = live.startsWith(base) ? live.slice(base.length) || "/" : pathname
    const at = areasAt(going)
    const shown = byHand[n.id] ?? inArea(n, n.sub, pathname)
    setToggled((s) => ({ at, open: { ...(s.at === at ? s.open : {}), [n.id]: !shown } }))
  }
  return (
    <div className="flex h-full flex-col">
      <nav aria-label={t("core.shell.main_nav")} className="flex min-h-0 flex-1 flex-col">
        <div className="flex h-14 items-center gap-2 px-4">
          <span className="grid size-8 place-items-center rounded-lg bg-tex-600 text-sm font-bold text-white dark:text-zinc-50" aria-hidden>
            T
          </span>
          <span className="truncate text-base font-semibold tracking-tight text-zinc-950">{boot.settings.brand_name || "TEX Engine"}</span>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto px-3 pb-4">
          {NAV_GROUPS.map((g) => {
            const groupItems = items.filter((i) => i.group === g.id)
            if (!groupItems.length) return null
            return (
              <div key={g.id}>
                <p className="px-2 pb-1 text-[11px] font-semibold tracking-wider text-zinc-500 uppercase">{t(g.label)}</p>
                <ul className="space-y-0.5">
                  {groupItems.map((n) =>
                    n.sub.length ? (
                      <NavArea
                        key={n.id}
                        item={n}
                        open={byHand[n.id] ?? inArea(n, n.sub, pathname)}
                        onToggle={() => toggle(n)}
                        onNavigate={onNavigate}
                      />
                    ) : (
                      <li key={n.id}>
                        <AreaLink item={n} onNavigate={onNavigate} />
                      </li>
                    ),
                  )}
                </ul>
              </div>
            )
          })}
        </div>
        {boot.settings.show_legacy_pms && (
          <div className="border-t border-zinc-200 px-3 py-3">
            <a
              href={toFullPath("/today")}
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
            >
              <ExternalLink className="size-4" aria-hidden />
              {t("core.nav.legacy_pms")}
            </a>
          </div>
        )}
      </nav>
      <SourceNotice sourceUrl={boot.settings.source_url} className="border-t border-zinc-200 px-5 py-2.5 text-[11px]" />
    </div>
  )
}

interface Command {
  id: string
  label: string
  hint?: string
  /** The area a sub-section belongs to, shown next to it. */
  area?: string
  run: () => void
}

interface FoundReservation {
  name: string
  property: string
  guest_name: string | null
  check_in_date: string
}

/** Reservations matching the palette's text (number, guest, e-mail, phone, channel reference), in
 * every hotel the user may see; debounced, at most six. */
function useReservationLookup(term: string): FoundReservation[] | undefined {
  const [found, setFound] = useState<{ q: string; rows: FoundReservation[] }>()
  const q = term.trim()
  useEffect(() => {
    if (q.length < 2) return
    let alive = true
    const h = window.setTimeout(() => {
      tex<FoundReservation[]>("crs", "reservations", { q, limit: 6 })
        .then((rows) => alive && setFound({ q, rows }))
        .catch(() => alive && setFound({ q, rows: [] }))
    }, 250)
    return () => {
      alive = false
      window.clearTimeout(h)
    }
  }, [q])
  return q.length >= 2 && found?.q === q ? found.rows : undefined
}

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTexT()
  const navigate = useNavigate()
  const items = useVisibleNav()
  const { canAnywhere, boot } = useSession()
  const confirmLeave = useConfirmLeave()
  const [q, setQ] = useState("")
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  const commands = useMemo<Command[]>(() => {
    const base: Command[] = items.flatMap((n) => [
      { id: n.id, label: t(n.label), hint: n.keywords, run: () => navigate(n.to) },
      // sub-sections (R-35), except the one that is the area's own page
      ...n.sub
        .filter((c) => !c.unavailable && childPath(c) !== n.to)
        .map((c) => ({ id: c.id, label: t(c.label), area: t(n.label), hint: `${c.keywords ?? ""} ${t(n.label)}`, run: () => navigate(c.to) })),
    ])
    if (items.some((n) => n.id === "crs"))
      base.unshift({ id: "new-booking", label: t("core.cmd.new_booking"), hint: "book reserve", run: () => navigate("/tex/crs") })
    const term = q.trim()
    if (term && items.some((n) => n.id === "reservations"))
      base.push({
        id: "find",
        label: t("core.cmd.find_reservation", { q: term }),
        // a number or a name is looked up in every hotel the user may see (the list names the hotel)
        run: () => navigate(`/tex/reservations?q=${encodeURIComponent(term)}&property=all`),
      })
    return base
  }, [items, q, t, navigate])
  const found = useReservationLookup(open && canAnywhere("reservation.view") ? q : "")
  const hotelOf = useMemo(() => new Map(boot.properties.map((p) => [p.name, p.property_name])), [boot.properties])
  const matches = useMemo<Command[]>(
    () =>
      (found ?? []).map((r) => ({
        id: `res-${r.name}`,
        label: `${r.guest_name || "—"} · ${r.name}`,
        area: `${fmtDate(r.check_in_date, "short")} · ${hotelOf.get(r.property) ?? r.property}`,
        run: () => navigate(`/tex/reservations/${encodeURIComponent(r.name)}`),
      })),
    [found, hotelOf, navigate],
  )

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase()
    if (!term) return commands
    // label prefix > label contains > keyword match; "find reservation" stays last
    const rank = (c: Command) => {
      const label = c.label.toLowerCase()
      if (c.id === "find") return 3
      if (label.startsWith(term)) return 0
      if (label.includes(term)) return 1
      return (c.hint ?? "").toLowerCase().includes(term) ? 2 : -1
    }
    const nav = commands
      .map((c) => ({ c, r: rank(c) }))
      .filter((x) => x.r >= 0)
      .sort((a, b) => a.r - b.r)
      .map((x) => x.c)
    // reservations found by number, name, e-mail, phone or channel reference: first when the term
    // looks like a number, an e-mail or a phone (never a page name), else after the pages
    const find = nav.filter((c) => c.id === "find")
    const pages = nav.filter((c) => c.id !== "find")
    return /[\d@]/.test(term) ? [...matches, ...pages, ...find] : [...pages, ...matches, ...find]
  }, [commands, q, matches])

  useEffect(() => {
    if (open) {
      setQ("")
      setActive(0)
      window.setTimeout(() => input.current?.focus(), 0)
    }
  }, [open])
  useEffect(() => setActive(0), [q])

  if (!open) return null
  const run = (c?: Command) => {
    if (!c) return
    if (!confirmLeave()) return
    onClose()
    c.run()
  }
  return (
    <div className="tex-root fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]">
      <div className="absolute inset-0 bg-black/40" aria-hidden onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-label={t("core.cmd.title")} className="relative w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-tex-pop">
        <div className="flex items-center gap-2 border-b border-zinc-200 px-3">
          <Search className="size-4 text-zinc-400" aria-hidden />
          <input
            ref={input}
            role="combobox"
            aria-label={t("core.cmd.title")}
            aria-expanded="true"
            aria-controls="tex-cmd-list"
            aria-activedescendant={filtered[active] ? `tex-cmd-${filtered[active].id}` : undefined}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault()
                setActive((a) => Math.min(a + 1, filtered.length - 1))
              } else if (e.key === "ArrowUp") {
                e.preventDefault()
                setActive((a) => Math.max(a - 1, 0))
              } else if (e.key === "Enter") {
                e.preventDefault()
                run(filtered[active])
              } else if (e.key === "Escape") onClose()
            }}
            placeholder={t("core.cmd.placeholder")}
            className="h-12 flex-1 bg-transparent text-sm text-zinc-900 outline-none placeholder:text-zinc-400"
          />
          <Kbd>Esc</Kbd>
        </div>
        <ul id="tex-cmd-list" role="listbox" className="max-h-80 overflow-y-auto p-1">
          {filtered.map((c, i) => (
            <li
              key={c.id}
              id={`tex-cmd-${c.id}`}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              onClick={() => run(c)}
              className={cn("flex cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm", i === active ? "bg-tex-50 text-tex-900" : "text-zinc-800")}
            >
              <span className="truncate">{c.label}</span>
              {c.area && <span className="shrink-0 text-xs text-zinc-500">{c.area}</span>}
            </li>
          ))}
          {!filtered.length && <li className="px-3 py-6 text-center text-sm text-zinc-500">{t("core.cmd.none")}</li>}
        </ul>
      </div>
    </div>
  )
}

/** Language + theme. In the header from `sm` up; inside the mobile drawer below. */
function Preferences({ idSuffix, className }: { idSuffix: string; className?: string }) {
  const { t, lang } = useTexT()
  const [theme, setThemeState] = useState(getTheme())
  const dark = theme === "dark" || (theme === "system" && document.documentElement.classList.contains("dark"))
  const id = `tex-lang-${idSuffix}`
  return (
    <div className={cn("flex items-center gap-1", className)}>
      <label className="sr-only" htmlFor={id}>
        {t("core.shell.language")}
      </label>
      <select
        id={id}
        value={lang}
        onChange={(e) => setTexLang(e.target.value as TexLang)}
        className="h-9 rounded-lg border border-transparent bg-transparent pr-7 pl-2 text-sm text-zinc-700 hover:border-zinc-200 focus:border-tex-500 focus:outline-none"
      >
        {TEX_LANGS.map((l) => (
          <option key={l.code} value={l.code}>
            {l.code.toUpperCase()} · {l.label}
          </option>
        ))}
      </select>
      <IconButton
        label={dark ? t("core.shell.theme_light") : t("core.shell.theme_dark")}
        icon={dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
        onClick={() => {
          const next = dark ? "light" : "dark"
          setTheme(next)
          setThemeState(next)
        }}
      />
    </div>
  )
}

function UserMenu() {
  const { boot } = useSession()
  const { signOut } = useAuth()
  const { t } = useTexT()
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Preferences idSuffix="header" className="hidden sm:flex" />
      <span className="mx-1 hidden max-w-[10rem] truncate text-sm text-zinc-600 lg:inline" title={boot.user.name}>
        {boot.user.full_name}
      </span>
      <IconButton label={t("core.shell.sign_out")} icon={<LogOut className="size-4" />} onClick={() => void signOut()} />
    </div>
  )
}

export function TexShell({ children }: { children: ReactNode }) {
  const { t } = useTexT()
  const { boot } = useSession()
  const [mobileNav, setMobileNav] = useState(false)
  const [palette, setPalette] = useState(false)
  const location = useLocation()

  useEffect(() => setMobileNav(false), [location.pathname])
  // a side panel opened in the shell starts under its top bar (tex.css, final follow-up)
  useEffect(() => {
    const root = document.documentElement
    root.dataset.texShell = ""
    return () => {
      delete root.dataset.texShell
    }
  }, [])
  // the tab says the brand (TEX Settings), never the upstream product (G-60)
  useEffect(() => {
    document.title = boot.settings.brand_name || "TEX Engine"
  }, [boot.settings.brand_name])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setPalette((p) => !p)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  return (
    <UnsavedChangesProvider message={t("core.unsaved.leave")}>
    <div className="tex-root min-h-screen bg-zinc-50 text-zinc-900">
      <a
        href="#tex-main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[70] focus:rounded-lg focus:bg-white focus:px-3 focus:py-2 focus:shadow-tex-pop"
      >
        {t("core.shell.skip")}
      </a>
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-zinc-200 bg-white lg:block">
        <Sidebar />
      </aside>
      {mobileNav && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" aria-hidden onClick={() => setMobileNav(false)} />
          <aside className="relative h-full w-72 max-w-[85vw] bg-white shadow-tex-pop">
            <div className="absolute top-3 right-3">
              <IconButton label={t("core.action.close")} icon={<X className="size-4" />} onClick={() => setMobileNav(false)} />
            </div>
            <div className="flex h-full flex-col">
              <div className="min-h-0 flex-1">
                <Sidebar onNavigate={() => setMobileNav(false)} />
              </div>
              <Preferences idSuffix="drawer" className="border-t border-zinc-200 px-3 py-3" />
            </div>
          </aside>
        </div>
      )}
      <div className="tex-page min-w-0 lg:pl-60">
        {/* tex-shell-bar: it keeps its whole width while a side panel sits beside the page (tex.css) */}
        <header className="tex-shell-bar sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-zinc-200 bg-white/90 px-3 backdrop-blur sm:px-5">
          <IconButton className="lg:hidden" label={t("core.shell.open_nav")} icon={<Menu className="size-5" />} onClick={() => setMobileNav(true)} />
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <HotelSwitcher />
            <TexModeBadge />
          </div>
          <button
            type="button"
            onClick={() => setPalette(true)}
            className="hidden h-9 items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-3 text-sm text-zinc-500 hover:border-zinc-300 md:flex"
          >
            <Search className="size-4" aria-hidden />
            {t("core.cmd.open")}
            <Kbd>Ctrl K</Kbd>
          </button>
          <IconButton className="md:hidden" label={t("core.cmd.open")} icon={<Search className="size-4" />} onClick={() => setPalette(true)} />
          <UserMenu />
        </header>
        <OnboardingBanner />
        <main id="tex-main" tabIndex={-1} className="mx-auto w-full max-w-[1400px] min-w-0 overflow-x-clip px-3 py-5 outline-none sm:px-6 sm:py-6">
          {children}
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
    </UnsavedChangesProvider>
  )
}
