import { useEffect, useMemo, useState } from "react"
import { Pencil, Plus, Power, PowerOff, Search, Trash2, UserPlus } from "lucide-react"
import { tex, useTexMutation, useTexQuery, type TexApiError } from "../../lib/api"
import { useSession } from "../../lib/session"
import { date, dateTime } from "../../lib/format"
import { useSiteToday } from "../../lib/siteDay"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Dialog,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  FormGrid,
  IconButton,
  InlineError,
  Input,
  Notice,
  Select,
  Skeleton,
  Switch,
  Textarea,
  useToast,
  type Tone,
} from "../../ui"
import { SettingsFrame } from "./SettingsFrame"
import { SCOPE_LEVELS, capLabel, scopeKey, type ScopeLevel } from "./capabilities"

export interface Grant {
  name: string
  user: string
  scope_level: ScopeLevel
  property: string | null
  hotel_group: string | null
  enterprise: string | null
  permission_profile: string
  valid_until: string | null
  disabled: number
  notes: string | null
  /** Hotels of the grant inside the viewer's own scope (others are only counted). */
  properties: string[]
  other_hotels?: number
  can_manage?: boolean
  manage_refusal?: string | null
}

interface UserRow {
  user: string
  full_name: string
  enabled: number
  last_login: string | null
  grants: Grant[]
}

interface UsersData {
  users: UserRow[]
  profiles: { name: string; profile_name: string; is_system: number }[]
}

export interface ProfilesData {
  profiles: { name: string; profile_name: string; description: string | null; is_system: number; capabilities: string[] }[]
  capabilities: Record<string, string>
}

type GrantDraft = Partial<Grant> & { user: string }

function grantState(g: Grant, today: string): { key: string; tone: Tone } {
  if (g.disabled) return { key: "settings.grant.state.disabled", tone: "neutral" }
  if (g.valid_until && g.valid_until < today) return { key: "settings.grant.state.expired", tone: "danger" }
  return { key: "settings.grant.state.active", tone: "success" }
}

function initials(name: string) {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase()
}

export default function UsersAccess() {
  const { t } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  const q = useTexQuery<UsersData>("admin", "users", {}, [])
  const profilesQ = useTexQuery<ProfilesData>("admin", "profiles", {}, [])
  const [search, setSearch] = useState("")
  const [level, setLevel] = useState("")
  const [editing, setEditing] = useState<GrantDraft | null>(null)
  const [inviting, setInviting] = useState(false)
  const [removing, setRemoving] = useState<Grant | null>(null)
  const [busyGrant, setBusyGrant] = useState<string | null>(null)
  // a grant is expired after its last day on the site's calendar, as the server counts it (G-91)
  const today = useSiteToday()
  const me = boot.user.name
  const platform = boot.user.platform_admin

  const propName = (p: string | null) => boot.properties.find((x) => x.name === p)?.property_name ?? p ?? "—"
  const target = (g: Grant) =>
    g.scope_level === "Hotel"
      ? propName(g.property)
      : g.scope_level === "Hotel Group"
        ? g.hotel_group
        : g.scope_level === "Enterprise"
          ? g.enterprise
          : t("settings.scope.all_hotels")

  const users = useMemo(() => {
    const s = search.trim().toLowerCase()
    return (q.data?.users ?? []).filter((u) => {
      if (level && !u.grants.some((g) => g.scope_level === level)) return false
      if (!s) return true
      return [u.user, u.full_name, ...u.grants.flatMap((g) => [g.permission_profile, target(g) ?? ""])].some((v) => v.toLowerCase().includes(s))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data, search, level])

  const toggle = async (g: Grant) => {
    setBusyGrant(g.name)
    try {
      await tex("admin", "save_grant", { data: { name: g.name, disabled: g.disabled ? 0 : 1 } }, { post: true })
      toast.success(g.disabled ? t("settings.grant.enabled_toast") : t("settings.grant.disabled_toast"))
      q.reload()
    } catch (e) {
      toast.error((e as TexApiError).message)
    } finally {
      setBusyGrant(null)
    }
  }

  return (
    <SettingsFrame
      subtitle={t("settings.users.subtitle")}
      actions={
        <>
          <Button variant="secondary" icon={<UserPlus className="size-4" aria-hidden />} onClick={() => setInviting(true)}>
            {t("settings.users.invite")}
          </Button>
          <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setEditing({ user: "", scope_level: "Hotel" })}>
            {t("settings.grant.add")}
          </Button>
        </>
      }
    >
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-400" aria-hidden />
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("settings.users.search")}
            aria-label={t("settings.users.search")}
            className="pl-9"
          />
        </div>
        <Field label={t("settings.grant.scope")} className="w-full sm:w-48">
          <Select
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            options={[{ value: "", label: t("core.label.all") }, ...SCOPE_LEVELS.map((l) => ({ value: l, label: t(scopeKey(l)) }))]}
          />
        </Field>
      </div>

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !q.data ? (
        <Card className="divide-y divide-zinc-100">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 p-4">
              <Skeleton className="size-9 rounded-full" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-64" />
              </div>
            </div>
          ))}
        </Card>
      ) : users.length === 0 ? (
        <Card>
          <EmptyState title={search || level ? t("settings.users.no_match") : t("settings.users.empty")} />
        </Card>
      ) : (
        <Card>
          <ul className="divide-y divide-zinc-100" aria-label={t("settings.users.list")}>
            {users.map((u) => {
              const self = u.user === me
              return (
                <li key={u.user} className="px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-tex-50 text-xs font-semibold text-tex-800">
                        {initials(u.full_name || u.user)}
                      </span>
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-900">
                          <span className="truncate">{u.full_name || u.user}</span>
                          {self && <Badge tone="brand">{t("settings.users.you")}</Badge>}
                          {!u.enabled && <Badge tone="danger">{t("settings.users.account_disabled")}</Badge>}
                        </p>
                        <p className="truncate text-xs text-zinc-500">
                          {u.user} · {u.last_login ? t("settings.users.last_login", { when: dateTime(u.last_login) }) : t("settings.users.never_logged_in")}
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Plus className="size-3.5" aria-hidden />}
                      onClick={() => setEditing({ user: u.user, scope_level: "Hotel" })}
                      disabled={self && !platform}
                      aria-label={`${t("settings.grant.add")}: ${u.full_name || u.user}`}
                    >
                      {t("settings.grant.add")}
                    </Button>
                  </div>
                  <ul className="mt-2 space-y-1.5 sm:pl-12" aria-label={t("settings.users.grants_of", { user: u.full_name || u.user })}>
                    {u.grants.map((g) => {
                      const st = grantState(g, today)
                      // the server says which grants this user may change (scope + held capabilities)
                      const locked = (self && !platform) || g.can_manage === false
                      return (
                        <li key={g.name} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-zinc-200 bg-zinc-50/60 px-3 py-2 text-sm">
                          <Badge tone="info">{t(scopeKey(g.scope_level))}</Badge>
                          <span className="min-w-0 font-medium text-zinc-900" title={g.properties.join(", ")}>
                            {target(g)}
                            {g.scope_level !== "Hotel" && (
                              <span className="ml-1 text-xs font-normal text-zinc-500">
                                ({t("settings.grant.hotels", { count: g.properties.length + (g.other_hotels ?? 0) })})
                              </span>
                            )}
                          </span>
                          <span className="text-zinc-600">{g.permission_profile}</span>
                          <span className="text-xs text-zinc-500">
                            {g.valid_until ? t("settings.grant.until", { date: date(g.valid_until) }) : t("settings.grant.no_end")}
                          </span>
                          <Badge tone={st.tone}>{t(st.key)}</Badge>
                          <span className="ml-auto flex items-center gap-0.5">
                            <IconButton
                              size="sm"
                              label={`${t("core.action.edit")}: ${g.permission_profile} · ${target(g)}`}
                              icon={<Pencil className="size-3.5" />}
                              disabled={locked}
                              onClick={() => setEditing(g)}
                            />
                            <IconButton
                              size="sm"
                              label={`${g.disabled ? t("settings.grant.enable") : t("settings.grant.disable")}: ${g.permission_profile} · ${target(g)}`}
                              icon={g.disabled ? <Power className="size-3.5" /> : <PowerOff className="size-3.5" />}
                              disabled={locked || busyGrant === g.name}
                              onClick={() => toggle(g)}
                            />
                            <IconButton
                              size="sm"
                              label={`${t("settings.grant.remove")}: ${g.permission_profile} · ${target(g)}`}
                              icon={<Trash2 className="size-3.5" />}
                              disabled={locked}
                              onClick={() => setRemoving(g)}
                            />
                          </span>
                          {!self && g.can_manage === false && g.manage_refusal && (
                            <p className="basis-full text-xs text-zinc-500">{g.manage_refusal}</p>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                  {self && !platform && <p className="mt-1.5 text-xs text-zinc-500 sm:pl-12">{t("settings.users.self_locked")}</p>}
                </li>
              )
            })}
          </ul>
        </Card>
      )}

      <GrantDrawer
        draft={editing}
        onClose={() => setEditing(null)}
        users={q.data?.users.map((u) => u.user) ?? []}
        profiles={profilesQ.data}
        profileNames={q.data?.profiles.map((p) => p.name) ?? []}
        onSaved={() => {
          setEditing(null)
          q.reload()
        }}
      />
      <InviteDialog
        open={inviting}
        onClose={() => setInviting(false)}
        onInvited={(email) => {
          setInviting(false)
          q.reload()
          setEditing({ user: email, scope_level: "Hotel" })
        }}
      />
      <ConfirmDialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        tone="danger"
        title={t("settings.grant.remove_title")}
        confirmLabel={t("settings.grant.remove")}
        body={removing ? t("settings.grant.remove_body", { user: removing.user, profile: removing.permission_profile, target: target(removing) ?? "" }) : null}
        onConfirm={async () => {
          if (!removing) return
          await tex("admin", "delete_grant", { name: removing.name }, { post: true })
          toast.success(t("settings.grant.removed_toast"))
          q.reload()
        }}
      />
    </SettingsFrame>
  )
}

// ─── grant editor ────────────────────────────────────────────────────────

function GrantDrawer({
  draft,
  onClose,
  onSaved,
  users,
  profiles,
  profileNames,
}: {
  draft: GrantDraft | null
  onClose: () => void
  onSaved: () => void
  users: string[]
  profiles?: ProfilesData
  profileNames: string[]
}) {
  const { t } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  const platform = boot.user.platform_admin
  const save = useTexMutation<{ data: Record<string, unknown> }, { name: string }>("admin", "save_grant")
  const [form, setForm] = useState<GrantDraft>({ user: "" })
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (draft) {
      setForm({ scope_level: "Hotel", ...draft })
      setTouched(false)
      save.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft])

  // targets I administer (the server enforces the same rule on save)
  const adminProps = boot.properties.filter((p) => platform || p.capabilities.includes("user.admin"))
  const uniq = (xs: (string | undefined | null)[]) => [...new Set(xs.filter(Boolean) as string[])].sort()
  const withCurrent = (opts: { value: string; label: string }[], cur?: string | null) =>
    cur && !opts.some((o) => o.value === cur) ? [...opts, { value: cur, label: cur }] : opts
  const level = (form.scope_level ?? "Hotel") as ScopeLevel
  const targetOptions =
    level === "Hotel"
      ? withCurrent(adminProps.map((p) => ({ value: p.name, label: p.property_name })), form.property)
      : level === "Hotel Group"
        ? withCurrent(uniq(adminProps.map((p) => p.hotel_group)).map((g) => ({ value: g, label: g })), form.hotel_group)
        : level === "Enterprise"
          ? withCurrent(uniq(adminProps.map((p) => p.enterprise)).map((e) => ({ value: e, label: e })), form.enterprise)
          : []
  const targetField = level === "Hotel" ? "property" : level === "Hotel Group" ? "hotel_group" : level === "Enterprise" ? "enterprise" : null
  const targetValue = targetField ? ((form[targetField] as string | null | undefined) ?? "") : ""

  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.user.trim()) || form.user === "Administrator"
  const errors = {
    user: !form.user.trim() ? t("settings.err.required") : !emailOk ? t("settings.err.email") : null,
    target: targetField && !targetValue ? t("settings.err.required") : null,
    profile: !form.permission_profile ? t("settings.err.required") : null,
  }
  const valid = !errors.user && !errors.target && !errors.profile
  const selectedProfile = profiles?.profiles.find((p) => p.name === form.permission_profile)
  const levels = SCOPE_LEVELS.filter((l) => l !== "Platform" || platform || form.scope_level === "Platform")

  const submit = async () => {
    setTouched(true)
    if (!valid) return
    const data: Record<string, unknown> = {
      user: form.user.trim(),
      scope_level: level,
      property: level === "Hotel" ? form.property : null,
      hotel_group: level === "Hotel Group" ? form.hotel_group : null,
      enterprise: level === "Enterprise" ? form.enterprise : null,
      permission_profile: form.permission_profile,
      valid_until: form.valid_until || null,
      disabled: form.disabled ? 1 : 0,
      notes: form.notes || null,
    }
    if (form.name) data.name = form.name
    try {
      await save.run({ data })
      toast.success(form.name ? t("settings.grant.saved_toast") : t("settings.grant.created_toast"))
      onSaved()
    } catch {
      /* shown inline */
    }
  }

  return (
    <Drawer
      open={!!draft}
      onClose={onClose}
      width="lg"
      title={form.name ? t("settings.grant.edit_title") : t("settings.grant.new_title")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={save.pending} onClick={submit}>
            {t("core.action.save")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-5"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        {save.error && (
          <Notice tone="danger" title={save.error.isPermission ? t("settings.grant.refused") : t("settings.grant.save_failed")}>
            <p className="whitespace-pre-line">{save.error.message}</p>
            {save.error.isPermission && <p className="mt-1 text-xs">{t("settings.grant.refused_hint")}</p>}
          </Notice>
        )}
        <Field label={t("settings.grant.user")} required error={touched ? errors.user : null} hint={!form.name ? t("settings.grant.user_hint") : undefined}>
          <Input
            type="email"
            list="tex-known-users"
            value={form.user}
            readOnly={!!form.name}
            className={form.name ? "bg-zinc-50 text-zinc-600" : undefined}
            autoComplete="off"
            onChange={(e) => setForm({ ...form, user: e.target.value })}
            data-autofocus={form.name ? undefined : true}
          />
        </Field>
        <datalist id="tex-known-users">
          {users.map((u) => (
            <option key={u} value={u} />
          ))}
        </datalist>
        <FormGrid>
          <Field label={t("settings.grant.scope")} required hint={t(`${scopeKey(level)}_hint`)}>
            <Select
              value={level}
              onChange={(e) => setForm({ ...form, scope_level: e.target.value as ScopeLevel })}
              options={levels.map((l) => ({ value: l, label: t(scopeKey(l)) }))}
            />
          </Field>
          {targetField ? (
            <Field label={t(`settings.grant.target.${targetField}`)} required error={touched ? errors.target : null}>
              <Select
                value={targetValue}
                placeholder={t("settings.select")}
                onChange={(e) => setForm({ ...form, [targetField]: e.target.value })}
                options={targetOptions}
              />
            </Field>
          ) : (
            <Notice tone="warning">{t("settings.grant.platform_warning")}</Notice>
          )}
        </FormGrid>
        <Field label={t("settings.grant.profile")} required error={touched ? errors.profile : null}>
          <Select
            value={form.permission_profile ?? ""}
            placeholder={t("settings.select")}
            onChange={(e) => setForm({ ...form, permission_profile: e.target.value })}
            options={profileNames.map((p) => ({ value: p, label: p }))}
          />
        </Field>
        {selectedProfile && (
          <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2">
            <p className="text-xs font-medium text-zinc-600">{t("settings.grant.profile_caps", { count: selectedProfile.capabilities.length })}</p>
            <ul className="mt-1.5 flex flex-wrap gap-1">
              {selectedProfile.capabilities.map((c) => (
                <li key={c}>
                  <Badge tone="neutral" title={c}>
                    {capLabel(t, c, profiles?.capabilities[c])}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
        <FormGrid>
          <Field label={t("settings.grant.valid_until")} hint={t("settings.grant.valid_until_hint")}>
            <Input type="date" value={form.valid_until ?? ""} onChange={(e) => setForm({ ...form, valid_until: e.target.value || null })} />
          </Field>
          <div className="pt-1 sm:pt-7">
            <Switch
              checked={!!form.disabled}
              onChange={(v) => setForm({ ...form, disabled: v ? 1 : 0 })}
              label={t("settings.grant.disabled")}
              description={t("settings.grant.disabled_hint")}
            />
          </div>
        </FormGrid>
        <Field label={t("settings.grant.notes")}>
          <Textarea value={form.notes ?? ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} maxLength={500} />
        </Field>
        <p className="text-xs text-zinc-500">{t("settings.grant.escalation_hint")}</p>
        <button type="submit" className="hidden" aria-hidden tabIndex={-1} />
      </form>
    </Drawer>
  )
}

// ─── invite ──────────────────────────────────────────────────────────────

function InviteDialog({ open, onClose, onInvited }: { open: boolean; onClose: () => void; onInvited: (email: string) => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const invite = useTexMutation<{ email: string; first_name: string; last_name?: string }, { user: string; existing: boolean }>("admin", "invite_user")
  const [email, setEmail] = useState("")
  const [first, setFirst] = useState("")
  const [last, setLast] = useState("")
  const [touched, setTouched] = useState(false)
  useEffect(() => {
    if (open) {
      setEmail("")
      setFirst("")
      setLast("")
      setTouched(false)
      invite.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const emailErr = !email.trim() ? t("settings.err.required") : !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) ? t("settings.err.email") : null
  const firstErr = !first.trim() ? t("settings.err.required") : null
  const submit = async () => {
    setTouched(true)
    if (emailErr || firstErr) return
    try {
      const r = await invite.run({ email: email.trim(), first_name: first.trim(), last_name: last.trim() || undefined })
      if (r.existing) toast.info(t("settings.invite.existing", { email: r.user }))
      else toast.success(t("settings.invite.sent", { email: r.user }))
      onInvited(r.user)
    } catch {
      /* inline */
    }
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t("settings.invite.title")}
      description={t("settings.invite.description")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={invite.pending} onClick={submit}>
            {t("settings.invite.submit")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <InlineError error={invite.error} />
        <Field label={t("settings.invite.email")} required error={touched ? emailErr : null}>
          <Input type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} data-autofocus />
        </Field>
        <FormGrid>
          <Field label={t("settings.invite.first_name")} required error={touched ? firstErr : null}>
            <Input value={first} onChange={(e) => setFirst(e.target.value)} maxLength={80} />
          </Field>
          <Field label={t("settings.invite.last_name")}>
            <Input value={last} onChange={(e) => setLast(e.target.value)} maxLength={80} />
          </Field>
        </FormGrid>
        <p className="text-xs text-zinc-500">{t("settings.invite.next_step")}</p>
        <button type="submit" className="hidden" aria-hidden tabIndex={-1} />
      </form>
    </Dialog>
  )
}
