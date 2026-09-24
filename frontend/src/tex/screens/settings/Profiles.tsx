import { Fragment, useEffect, useMemo, useState } from "react"
import { Check, Minus, Pencil, Plus, ShieldAlert } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  InlineError,
  Input,
  Notice,
  Skeleton,
  Textarea,
  useToast,
} from "../../ui"
import { cn } from "../../../lib/utils"
import { SettingsFrame } from "./SettingsFrame"
import { ANY_CHANNEL, SENSITIVE, capLabel, channelSummary, groupCapabilities } from "./capabilities"
import type { ProfilesData } from "./UsersAccess"
import { useLabels } from "../crs/lib/labels"

type Profile = ProfilesData["profiles"][number]

export default function Profiles() {
  const { t } = useTexT()
  const { boot } = useSession()
  const platform = boot.user.platform_admin
  const q = useTexQuery<ProfilesData>("admin", "profiles", {}, [])
  const [editing, setEditing] = useState<Partial<Profile> | null>(null)
  const d = q.data
  const groups = useMemo(() => (d ? groupCapabilities(Object.keys(d.capabilities)) : []), [d])
  const L = useLabels()
  const channelText = (p: Profile) => channelSummary(t, L.channel, p)

  return (
    <SettingsFrame
      subtitle={t("settings.profiles.subtitle")}
      actions={
        platform ? (
          <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setEditing({ capabilities: [] })}>
            {t("settings.profiles.new")}
          </Button>
        ) : undefined
      }
    >
      {!platform && (
        <div className="mb-4">
          <Notice tone="info">{t("settings.profiles.read_only")}</Notice>
        </div>
      )}
      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !d ? (
        <Card className="space-y-2 p-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </Card>
      ) : d.profiles.length === 0 ? (
        <Card>
          <EmptyState title={t("settings.profiles.empty")} />
        </Card>
      ) : (
        <Card>
          <CardHeader title={t("settings.profiles.matrix")} description={t("settings.profiles.matrix_hint")} />
          <div className="overflow-x-auto">
            <table className="min-w-full border-separate border-spacing-0 text-sm">
              <caption className="sr-only">{t("settings.profiles.matrix_caption")}</caption>
              <thead>
                <tr>
                  <th
                    scope="col"
                    className="sticky left-0 z-[2] min-w-44 border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-left text-xs font-semibold tracking-wide text-zinc-600 uppercase sm:min-w-64"
                  >
                    {t("settings.profiles.capability")}
                  </th>
                  {d.profiles.map((p) => (
                    <th key={p.name} scope="col" className="min-w-24 border-b border-zinc-200 bg-zinc-50 px-1.5 py-2 text-center align-bottom">
                      <span className="block text-xs font-semibold text-zinc-800">{p.profile_name}</span>
                      <span className="mt-0.5 block text-[11px] font-normal text-zinc-500">
                        {t("settings.profiles.cap_count", { count: p.capabilities.length })}
                      </span>
                      {p.is_system ? (
                        <Badge tone="neutral" className="mt-1">
                          {t("settings.profiles.system")}
                        </Badge>
                      ) : null}
                      {platform && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="mt-1"
                          icon={<Pencil className="size-3" aria-hidden />}
                          aria-label={`${t("core.action.edit")}: ${p.profile_name}`}
                          onClick={() => setEditing(p)}
                        >
                          {t("core.action.edit")}
                        </Button>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <Fragment key={g.id}>
                    <tr>
                      <th
                        scope="colgroup"
                        colSpan={d.profiles.length + 1}
                        className="border-b border-zinc-100 bg-white px-3 pt-4 pb-1.5 text-left"
                      >
                        <span className="sticky left-3 block max-w-[80vw]">
                          <span className="block text-xs font-semibold tracking-wide text-tex-700 uppercase">{t(`settings.capgroup.${g.id}`)}</span>
                          <span className="block text-xs font-normal text-zinc-500">{t(`settings.capgroup.${g.id}_hint`)}</span>
                        </span>
                      </th>
                    </tr>
                    {g.caps.map((c) => (
                      <tr key={c} className="group">
                        <th scope="row" className="sticky left-0 z-[1] border-b border-zinc-100 bg-white px-3 py-1.5 text-left font-normal group-hover:bg-zinc-50">
                          <span className="flex items-center gap-1.5 text-zinc-900">
                            {capLabel(t, c, d.capabilities[c])}
                            {SENSITIVE.has(c) && (
                              <ShieldAlert className="size-3.5 shrink-0 text-amber-600" aria-label={t("settings.profiles.sensitive")} role="img" />
                            )}
                          </span>
                          <span className="font-mono text-[11px] text-zinc-400">{c}</span>
                        </th>
                        {d.profiles.map((p) => {
                          const on = p.capabilities.includes(c)
                          return (
                            <td key={p.name} className="border-b border-zinc-100 px-2 py-1.5 text-center group-hover:bg-zinc-50">
                              {on ? (
                                <Check className="mx-auto size-4 text-emerald-600" aria-label={t("core.label.yes")} role="img" />
                              ) : (
                                <Minus className="mx-auto size-4 text-zinc-300" aria-label={t("core.label.no")} role="img" />
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </Fragment>
                ))}
                <tr>
                  <th scope="colgroup" colSpan={d.profiles.length + 1} className="border-b border-zinc-100 bg-white px-3 pt-4 pb-1.5 text-left">
                    <span className="sticky left-3 block max-w-[80vw]">
                      <span className="block text-xs font-semibold tracking-wide text-tex-700 uppercase">{t("settings.profiles.channels")}</span>
                      <span className="block text-xs font-normal text-zinc-500">{t("settings.profiles.channels_hint")}</span>
                    </span>
                  </th>
                </tr>
                <tr className="group">
                  <th scope="row" className="sticky left-0 z-[1] border-b border-zinc-100 bg-white px-3 py-1.5 text-left font-normal group-hover:bg-zinc-50">
                    {t("settings.profiles.channels_row")}
                  </th>
                  {d.profiles.map((p) => (
                    <td key={p.name} data-profile-channels={p.name} className="border-b border-zinc-100 px-2 py-1.5 text-center text-xs text-zinc-700 group-hover:bg-zinc-50">
                      {channelText(p)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="flex items-center gap-1.5 border-t border-zinc-100 px-4 py-2.5 text-xs text-zinc-500">
            <ShieldAlert className="size-3.5 text-amber-600" aria-hidden />
            {t("settings.profiles.sensitive_legend")}
          </p>
        </Card>
      )}
      {d && (
        <ProfileDrawer
          profile={editing}
          capabilities={d.capabilities}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            q.reload()
          }}
        />
      )}
    </SettingsFrame>
  )
}

function ProfileDrawer({
  profile,
  capabilities,
  onClose,
  onSaved,
}: {
  profile: Partial<Profile> | null
  capabilities: Record<string, string>
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const save = useTexMutation<{ data: Record<string, unknown> }, { name: string }>("admin", "save_profile")
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [caps, setCaps] = useState<Set<string>>(new Set())
  const [channels, setChannels] = useState<Set<string>>(new Set())
  const [touched, setTouched] = useState(false)
  const groups = useMemo(() => groupCapabilities(Object.keys(capabilities)), [capabilities])
  const { boot } = useSession()
  const L = useLabels()

  useEffect(() => {
    if (!profile) return
    setName(profile.profile_name ?? "")
    setDescription(profile.description ?? "")
    setCaps(new Set(profile.capabilities ?? []))
    setChannels(new Set(profile.sales_channels ?? []))
    setTouched(false)
    save.clearError()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile])

  const nameErr = !name.trim() ? t("settings.err.required") : null
  const toggle = (c: string, on: boolean) => {
    const next = new Set(caps)
    if (on) next.add(c)
    else next.delete(c)
    setCaps(next)
  }
  const submit = async () => {
    setTouched(true)
    if (nameErr) return
    const data: Record<string, unknown> = {
      profile_name: name.trim(),
      description: description.trim(),
      capabilities: [...caps].sort(),
      sales_channels: [...channels].sort(),
    }
    if (profile?.name) data.name = profile.name
    try {
      await save.run({ data })
      toast.success(t("settings.profiles.saved"))
      onSaved()
    } catch {
      /* inline */
    }
  }

  return (
    <Drawer
      open={!!profile}
      onClose={onClose}
      width="lg"
      title={profile?.name ? t("settings.profiles.edit_title", { name: profile.profile_name ?? "" }) : t("settings.profiles.new")}
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
      <div className="space-y-5">
        <InlineError error={save.error} />
        {profile?.is_system ? <Notice tone="warning">{t("settings.profiles.system_warning")}</Notice> : null}
        <Field label={t("settings.profiles.name")} required error={touched ? nameErr : null}>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={140} data-autofocus />
        </Field>
        <Field label={t("settings.profiles.description")}>
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} rows={2} />
        </Field>
        <p className="text-sm text-zinc-600">{t("settings.profiles.selected", { count: caps.size })}</p>
        {groups.map((g) => {
          const all = g.caps.every((c) => caps.has(c))
          return (
            <fieldset key={g.id} className="rounded-lg border border-zinc-200">
              <legend className="sr-only">{t(`settings.capgroup.${g.id}`)}</legend>
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-100 bg-zinc-50 px-3 py-2">
                <div>
                  <p className="text-xs font-semibold tracking-wide text-tex-700 uppercase" aria-hidden>
                    {t(`settings.capgroup.${g.id}`)}
                  </p>
                  <p className="text-xs text-zinc-500">{t(`settings.capgroup.${g.id}_hint`)}</p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    const next = new Set(caps)
                    for (const c of g.caps) {
                      if (all) next.delete(c)
                      else next.add(c)
                    }
                    setCaps(next)
                  }}
                >
                  {all ? t("settings.profiles.clear_group") : t("settings.profiles.select_group")}
                </Button>
              </div>
              <ul className="divide-y divide-zinc-100">
                {g.caps.map((c) => (
                  <li key={c}>
                    <label className={cn("flex cursor-pointer items-start gap-3 px-3 py-2 hover:bg-zinc-50")}>
                      <input
                        type="checkbox"
                        className="mt-0.5 size-4 accent-tex-600"
                        checked={caps.has(c)}
                        onChange={(e) => toggle(c, e.target.checked)}
                      />
                      <span className="min-w-0">
                        <span className="flex items-center gap-1.5 text-sm text-zinc-900">
                          {capLabel(t, c, capabilities[c])}
                          {SENSITIVE.has(c) && <Badge tone="warning">{t("settings.profiles.sensitive")}</Badge>}
                        </span>
                        <span className="font-mono text-[11px] text-zinc-400">{c}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </fieldset>
          )
        })}
        <fieldset className="rounded-lg border border-zinc-200">
          <legend className="sr-only">{t("settings.profiles.channels")}</legend>
          <div className="border-b border-zinc-100 bg-zinc-50 px-3 py-2">
            <p className="text-xs font-semibold tracking-wide text-tex-700 uppercase" aria-hidden>
              {t("settings.profiles.channels")}
            </p>
            <p className="text-xs text-zinc-500">{t("settings.profiles.channels_edit_hint")}</p>
          </div>
          {caps.has(ANY_CHANNEL) && (
            <div className="px-3 pt-2">
              <Notice tone="info">{t("settings.profiles.channels_any_note")}</Notice>
            </div>
          )}
          <ul className="divide-y divide-zinc-100">
            {boot.channels.map((c) => (
              <li key={c.name}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-zinc-50">
                  <input
                    type="checkbox"
                    className="size-4 accent-tex-600"
                    checked={channels.has(c.name)}
                    onChange={(e) => {
                      const next = new Set(channels)
                      if (e.target.checked) next.add(c.name)
                      else next.delete(c.name)
                      setChannels(next)
                    }}
                  />
                  <span className="text-sm text-zinc-900">{L.channel(c.name) !== c.name ? L.channel(c.name) : c.channel_name || c.name}</span>
                  <span className="font-mono text-[11px] text-zinc-400">{c.name}</span>
                </label>
              </li>
            ))}
          </ul>
          {!channels.size && !caps.has(ANY_CHANNEL) && <p className="px-3 py-2 text-xs text-zinc-500">{t("settings.profiles.channels_default_note")}</p>}
        </fieldset>
      </div>
    </Drawer>
  )
}
