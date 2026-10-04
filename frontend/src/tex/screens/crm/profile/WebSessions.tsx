import { LogOut } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../../lib/api"
import { dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, InlineError, useToast } from "../../../ui"
import type { MemberSession } from "../types"

/** The guest's sign-ins on the booking sites (C-04, ADR-078; batch 2O): where, since and until when. Staff who may
 * edit the guest at a session's hotel sign them out of one device or of every one (a lost phone, a shared computer);
 * the server lists only the sites of the hotels the user sees the guest through, and never a token. */
export function WebSessions({ guest }: { guest: string }) {
  const { t } = useTexT()
  const toast = useToast()
  const q = useTexQuery<MemberSession[]>("crm", "member_sessions", { guest }, [guest])
  const end = useTexMutation<{ guest: string; session?: string }, { ended: number }>("crm", "end_member_sessions")
  const rows = q.data ?? []
  if (!rows.length && !q.error) return null
  // the server says which the user may end (an open session of a hotel where they edit the guest; review round 1)
  const endable = rows.filter((r) => r.can_end)
  const signOut = async (session?: string) => {
    try {
      const out = await end.run({ guest, ...(session ? { session } : {}) })
      toast.success(t("crm.sessions.ended", { count: out.ended }))
      q.reload()
    } catch {
      /* inline */
    }
  }
  return (
    <section aria-label={t("crm.sessions.title")} className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-zinc-900">{t("crm.sessions.title")}</h3>
        {endable.length > 1 && (
          <Button variant="secondary" size="sm" icon={<LogOut className="size-4" aria-hidden />} loading={end.pending} onClick={() => signOut()}>
            {t("crm.sessions.end_all")}
          </Button>
        )}
      </div>
      <p className="text-xs text-zinc-500">{t("crm.sessions.hint")}</p>
      {rows.length > 0 && (
        <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
          {rows.map((r) => (
            <li key={r.name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="font-medium text-zinc-900">{r.site_name}</span>
                <Badge tone={r.active ? "success" : "neutral"}>{t(r.active ? "crm.sessions.active" : "crm.sessions.over")}</Badge>
                <span className="text-xs text-zinc-500">{t("crm.sessions.since", { date: dateTime(r.signed_in_at) })}</span>
                <span className="text-xs text-zinc-500">
                  {r.signed_out_at
                    ? t("crm.sessions.signed_out", { date: dateTime(r.signed_out_at) })
                    : t(r.active ? "crm.sessions.until" : "crm.sessions.expired", { date: dateTime(r.expires_at) })}
                </span>
              </div>
              {r.can_end && (
                <Button variant="ghost" size="sm" disabled={end.pending} onClick={() => signOut(r.name)}>
                  {t("crm.sessions.end")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <InlineError error={end.error ?? q.error} />
    </section>
  )
}
