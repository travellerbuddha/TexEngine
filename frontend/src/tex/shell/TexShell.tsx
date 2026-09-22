import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { NavLink, useLocation, useNavigate } from "react-router-dom"
import { Building2, ExternalLink, LogOut, Menu, Moon, Search, Sun, X } from "lucide-react"
import { cn } from "../../lib/utils"
import { useAuth } from "../../lib/auth"
import { getTheme, setTheme } from "../../lib/theme"
import { toFullPath } from "../../lib/routing"
import { NAV, NAV_GROUPS, type NavItem } from "./nav"
import { useSession } from "../lib/session"
import { setTexLang, TEX_LANGS, useTexT, type TexLang } from "../i18n"
import { IconButton, Kbd } from "../ui"

function useVisibleNav(): NavItem[] {
  const { can } = useSession()
  return NAV.filter((n) => n.anyOf.some((c) => can(c)))
}

function HotelSwitcher() {
  const { boot, property, setProperty } = useSession()
  const { t } = useTexT()
  if (boot.properties.length <= 1)
    return (
      <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-zinc-800">
        <Building2 className="size-4 shrink-0 text-zinc-500" aria-hidden />
        <span className="truncate">{property?.property_name ?? t("core.shell.no_hotel")}</span>
      </div>
    )
  return (
    <label className="flex min-w-0 items-center gap-2">
      <Building2 className="size-4 shrink-0 text-zinc-500" aria-hidden />
      <span className="sr-only">{t("core.shell.hotel")}</span>
      <select
        value={property?.name ?? ""}
        onChange={(e) => setProperty(e.target.value)}
        className="h-9 max-w-[16rem] truncate rounded-lg border border-zinc-300 bg-white pr-8 pl-2 text-sm font-medium text-zinc-900 focus:border-tex-500 focus:ring-2 focus:ring-tex-500/30 focus:outline-none"
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

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const items = useVisibleNav()
  const { boot } = useSession()
  const { t } = useTexT()
  return (
    <nav aria-label={t("core.shell.main_nav")} className="flex h-full flex-col">
      <div className="flex h-14 items-center gap-2 px-4">
        <span className="grid size-8 place-items-center rounded-lg bg-tex-600 text-sm font-bold text-white dark:text-zinc-50" aria-hidden>
          T
        </span>
        <span className="text-base font-semibold tracking-tight text-zinc-950">{boot.settings.brand_name || "TEX Engine"}</span>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-3 pb-4">
        {NAV_GROUPS.map((g) => {
          const groupItems = items.filter((i) => i.group === g.id)
          if (!groupItems.length) return null
          return (
            <div key={g.id}>
              <p className="px-2 pb-1 text-[11px] font-semibold tracking-wider text-zinc-400 uppercase">{t(g.label)}</p>
              <ul className="space-y-0.5">
                {groupItems.map((n) => (
                  <li key={n.id}>
                    <NavLink
                      to={n.to}
                      end={n.to === "/tex" || n.id === "crs"}
                      onClick={onNavigate}
                      className={({ isActive }) =>
                        cn(
                          "flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm font-medium transition-colors",
                          isActive ? "bg-tex-50 text-tex-800" : "text-zinc-700 hover:bg-zinc-100 hover:text-zinc-950",
                        )
                      }
                    >
                      <n.icon className="size-4 shrink-0" aria-hidden />
                      {t(n.label)}
                    </NavLink>
                  </li>
                ))}
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
  )
}

interface Command {
  id: string
  label: string
  hint?: string
  run: () => void
}

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTexT()
  const navigate = useNavigate()
  const items = useVisibleNav()
  const [q, setQ] = useState("")
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  const commands = useMemo<Command[]>(() => {
    const base: Command[] = items.map((n) => ({
      id: n.id,
      label: t(n.label),
      hint: n.keywords,
      run: () => navigate(n.to),
    }))
    if (items.some((n) => n.id === "crs"))
      base.unshift({ id: "new-booking", label: t("core.cmd.new_booking"), hint: "book reserve", run: () => navigate("/tex/crs") })
    const term = q.trim()
    if (term && items.some((n) => n.id === "reservations"))
      base.push({
        id: "find",
        label: t("core.cmd.find_reservation", { q: term }),
        run: () => navigate(`/tex/reservations?q=${encodeURIComponent(term)}`),
      })
    return base
  }, [items, q, t, navigate])

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase()
    if (!term) return commands
    return commands.filter((c) => c.id === "find" || `${c.label} ${c.hint ?? ""}`.toLowerCase().includes(term))
  }, [commands, q])

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
              className={cn("cursor-pointer rounded-lg px-3 py-2 text-sm", i === active ? "bg-tex-50 text-tex-900" : "text-zinc-800")}
            >
              {c.label}
            </li>
          ))}
          {!filtered.length && <li className="px-3 py-6 text-center text-sm text-zinc-500">{t("core.cmd.none")}</li>}
        </ul>
      </div>
    </div>
  )
}

function UserMenu() {
  const { boot } = useSession()
  const { signOut } = useAuth()
  const { t, lang } = useTexT()
  const [theme, setThemeState] = useState(getTheme())
  const dark = theme === "dark" || (theme === "system" && document.documentElement.classList.contains("dark"))
  return (
    <div className="flex items-center gap-1">
      <label className="sr-only" htmlFor="tex-lang">
        {t("core.shell.language")}
      </label>
      <select
        id="tex-lang"
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
      <span className="mx-1 hidden max-w-[10rem] truncate text-sm text-zinc-600 lg:inline" title={boot.user.name}>
        {boot.user.full_name}
      </span>
      <IconButton label={t("core.shell.sign_out")} icon={<LogOut className="size-4" />} onClick={() => void signOut()} />
    </div>
  )
}

export function TexShell({ children }: { children: ReactNode }) {
  const { t } = useTexT()
  const [mobileNav, setMobileNav] = useState(false)
  const [palette, setPalette] = useState(false)
  const location = useLocation()

  useEffect(() => setMobileNav(false), [location.pathname])
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
            <Sidebar onNavigate={() => setMobileNav(false)} />
          </aside>
        </div>
      )}
      <div className="lg:pl-60">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-zinc-200 bg-white/90 px-3 backdrop-blur sm:px-5">
          <IconButton className="lg:hidden" label={t("core.shell.open_nav")} icon={<Menu className="size-5" />} onClick={() => setMobileNav(true)} />
          <div className="min-w-0 flex-1">
            <HotelSwitcher />
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
        <main id="tex-main" tabIndex={-1} className="mx-auto w-full max-w-[1400px] px-3 py-5 outline-none sm:px-6 sm:py-6">
          {children}
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  )
}
