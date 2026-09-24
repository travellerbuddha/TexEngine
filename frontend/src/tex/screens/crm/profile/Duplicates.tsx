import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { GitMerge } from "lucide-react"
import { useTexMutation } from "../../../lib/api"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, Dialog, Field, InlineError, Input, Notice, useToast } from "../../../ui"
import { useEvent } from "../lib"
import type { Guest, MergeResult, PossibleDuplicate } from "../types"

/** Profiles that may be the same person (same phone or e-mail), with a merge into this one (ADR-056 second review). */
export function DuplicatesCard({ duplicates, canEdit, onMerge }: { duplicates: PossibleDuplicate[]; canEdit: boolean; onMerge: (source: string) => void }) {
  const { t } = useTexT()
  if (!duplicates.length) return null
  return (
    <Card>
      <CardHeader title={t("crm.merge.duplicates")} description={t("crm.merge.duplicates_hint")} />
      <CardBody>
        <ul className="divide-y divide-zinc-100" aria-label={t("crm.merge.duplicates")}>
          {duplicates.map((d) => (
            <li key={d.name} className="flex flex-wrap items-center gap-2 py-2 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1">
                <Link to={`/tex/crm/guests/${encodeURIComponent(d.name)}`} className="text-sm font-medium text-tex-700 hover:underline">
                  {d.full_name || d.name}
                </Link>
                <p className="flex flex-wrap items-center gap-1 text-xs text-zinc-500">
                  <span>{d.name}</span>
                  {d.match.map((m) => (
                    <Badge key={m} tone="warning">
                      {t(`crm.merge.same_${m}`)}
                    </Badge>
                  ))}
                </p>
              </div>
              {canEdit && (
                <Button size="sm" variant="secondary" icon={<GitMerge className="size-4" aria-hidden />} onClick={() => onMerge(d.name)}>
                  {t("crm.merge.merge_here")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  )
}

export function MergeDialog({
  open,
  guest,
  source: initialSource,
  onClose,
  onMerged,
}: {
  open: boolean
  guest: Guest
  /** the duplicate to merge into ``guest`` (typed by the user when empty) */
  source: string
  onClose: () => void
  onMerged: (r: MergeResult) => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const [source, setSource] = useState(initialSource)
  const m = useTexMutation<{ source: string; target: string }, MergeResult>("crm", "merge_guests")
  const close = useEvent(() => {
    if (!m.pending) onClose()
  })
  useEffect(() => {
    if (open) {
      setSource(initialSource)
      m.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialSource])
  const valid = Boolean(source.trim()) && source.trim() !== guest.name
  const submit = async () => {
    if (!valid) return
    try {
      const r = await m.run({ source: source.trim(), target: guest.name })
      toast.success(t("crm.merge.done", { source: r.source }))
      onMerged(r)
      onClose()
    } catch {
      /* inline */
    }
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("crm.merge.title", { name: guest.full_name || guest.name })}
      description={t("crm.merge.desc")}
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={m.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button variant="danger" loading={m.pending} disabled={!valid} onClick={submit}>
            {t("crm.merge.confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("crm.merge.source")} required hint={t("crm.merge.source_hint")}>
          <Input value={source} onChange={(e) => setSource(e.target.value)} maxLength={140} autoComplete="off" data-autofocus />
        </Field>
        <Notice tone="warning" title={t("crm.merge.what_title")}>
          <ul className="list-disc space-y-1 pl-4">
            <li>{t("crm.merge.what_moves")}</li>
            <li>{t("crm.merge.what_consent")}</li>
            <li>{t("crm.merge.what_final")}</li>
          </ul>
        </Notice>
        <InlineError error={m.error} />
      </div>
    </Dialog>
  )
}
