import { useEffect, useState } from "react"
import { tex, TexApiError, useTexMutation } from "../../../lib/api"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, ConfirmDialog, Dialog, Field, InlineError, Input, Notice, Select, Spinner, Textarea, useToast } from "../../../ui"
import { IssueList } from "../components/common"
import type { ValidationResult, VersionRow } from "../lib/types"
import { toFrappeDatetime, versionLabel } from "../lib/util"

/** Publish a draft: server validation first (errors block, warnings need a
 * confirmation), then an effective time and a change note for the audit trail. */
export function PublishDialog({
  open,
  onClose,
  version,
  contractCode,
  onDone,
}: {
  open: boolean
  onClose: () => void
  version: { name: string; version_no: number }
  contractCode: string
  onDone: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const publish = useTexMutation<{ name: string; effective_from: string | null; change_note: string }>("contracts", "publish_version")
  const [check, setCheck] = useState<ValidationResult>()
  const [checkErr, setCheckErr] = useState<TexApiError>()
  const [checking, setChecking] = useState(false)
  const [when, setWhen] = useState<"now" | "later">("now")
  const [at, setAt] = useState("")
  const [note, setNote] = useState("")
  const [ack, setAck] = useState(false)

  const runCheck = () => {
    setChecking(true)
    setCheckErr(undefined)
    tex<ValidationResult>("contracts", "validate_version", { name: version.name })
      .then(setCheck)
      .catch((e: unknown) => setCheckErr(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error")))
      .finally(() => setChecking(false))
  }
  useEffect(() => {
    if (!open) return
    setCheck(undefined)
    setWhen("now")
    setAt("")
    setNote("")
    setAck(false)
    publish.clearError()
    runCheck()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, version.name])

  const errors = check?.issues.filter((i) => i.level === "ERROR").length ?? 0
  const warnings = check?.issues.filter((i) => i.level !== "ERROR").length ?? 0
  const ready = Boolean(check) && errors === 0 && (warnings === 0 || ack) && note.trim().length >= 3 && (when === "now" || Boolean(at))

  const submit = async () => {
    if (!ready) return
    try {
      await publish.run({ name: version.name, effective_from: when === "later" ? toFrappeDatetime(at) : null, change_note: note.trim() })
      toast.success(t("rates.version.published", { v: versionLabel(version.name, version.version_no), code: contractCode }))
      onDone()
      onClose()
    } catch {
      /* inline */
    }
  }

  return (
    <Dialog
      open={open}
      onClose={publish.pending ? () => undefined : onClose}
      size="lg"
      title={t("rates.version.publish_title", { v: versionLabel(version.name, version.version_no), code: contractCode })}
      description={t("rates.version.publish_desc")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={publish.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button onClick={submit} loading={publish.pending} disabled={!ready}>
            {when === "later" ? t("rates.version.schedule") : t("rates.version.publish")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <section aria-labelledby="pub-check" className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 id="pub-check" className="text-sm font-semibold text-zinc-900">
              {t("rates.version.server_check")}
            </h3>
            <Button variant="ghost" size="sm" onClick={runCheck} disabled={checking}>
              {t("rates.version.recheck")}
            </Button>
          </div>
          {checking && !check ? (
            <p className="flex items-center gap-2 text-sm text-zinc-500">
              <Spinner /> {t("rates.version.checking")}
            </p>
          ) : checkErr ? (
            <InlineError error={checkErr} />
          ) : (
            <IssueList issues={check?.issues} emptyOk={t("rates.version.check_ok")} />
          )}
          {errors > 0 && <p className="text-sm text-rose-800">{t("rates.version.fix_errors")}</p>}
          {errors === 0 && warnings > 0 && (
            <Checkbox label={t("rates.version.ack_warnings", { count: warnings })} checked={ack} onChange={(e) => setAck(e.target.checked)} />
          )}
        </section>
        <fieldset className="space-y-2">
          <legend className="text-sm font-semibold text-zinc-900">{t("rates.version.effective")}</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="inline-flex items-center gap-2">
              <input type="radio" name="pub-when" checked={when === "now"} onChange={() => setWhen("now")} className="accent-tex-600" />
              {t("rates.version.effective_now")}
            </label>
            <label className="inline-flex items-center gap-2">
              <input type="radio" name="pub-when" checked={when === "later"} onChange={() => setWhen("later")} className="accent-tex-600" />
              {t("rates.version.effective_later")}
            </label>
          </div>
          {when === "later" && (
            <Field label={t("rates.f.effective_from")} required hint={t("rates.h.effective_from")}>
              <Input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} className="sm:w-64" />
            </Field>
          )}
        </fieldset>
        <Field label={t("rates.f.change_note")} required hint={t("rates.h.change_note")}>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={500} />
        </Field>
        <Notice tone="info">{t("rates.version.publish_notice")}</Notice>
        <InlineError error={publish.error} />
      </div>
    </Dialog>
  )
}

/** Create the contract's single draft, copied from a chosen version. */
export function NewDraftDialog({
  open,
  onClose,
  contract,
  versions,
  basedOn,
  onDone,
}: {
  open: boolean
  onClose: () => void
  contract: string
  versions: VersionRow[]
  basedOn?: string
  onDone: (version: string) => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const create = useTexMutation<{ contract: string; based_on: string | null }, { version: string }>("contracts", "new_draft")
  const [base, setBase] = useState("")
  useEffect(() => {
    if (open) {
      setBase(basedOn ?? versions[0]?.name ?? "")
      create.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, basedOn])
  const submit = async () => {
    try {
      const r = await create.run({ contract, based_on: base || null })
      toast.success(t("rates.version.draft_created"))
      onDone(r.version)
      onClose()
    } catch {
      /* inline */
    }
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t("rates.version.new_draft")}
      description={t("rates.version.new_draft_desc")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button onClick={submit} loading={create.pending}>
            {t("rates.version.create_draft")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {versions.length > 0 ? (
          <Field label={t("rates.f.based_on")} hint={t("rates.h.based_on")}>
            <Select
              value={base}
              onChange={(e) => setBase(e.target.value)}
              options={versions.map((v) => ({ value: v.name, label: `${versionLabel(v.name, v.version_no)} · ${t(`rates.version_status.${v.status}`)}` }))}
            />
          </Field>
        ) : (
          <p className="text-sm text-zinc-600">{t("rates.version.first_draft")}</p>
        )}
        <InlineError error={create.error} />
      </div>
    </Dialog>
  )
}

/** Withdraw a published version (audited; reason required). */
export function WithdrawDialog({
  open,
  onClose,
  version,
  onDone,
}: {
  open: boolean
  onClose: () => void
  version: { name: string; version_no: number }
  onDone: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  return (
    <ConfirmDialog
      open={open}
      onClose={onClose}
      tone="danger"
      requireReason
      title={t("rates.version.withdraw_title", { v: versionLabel(version.name, version.version_no) })}
      body={t("rates.version.withdraw_body")}
      confirmLabel={t("rates.version.withdraw")}
      onConfirm={async (reason) => {
        await tex("contracts", "withdraw_version", { name: version.name, reason }, { post: true })
        toast.success(t("rates.version.withdrawn", { v: versionLabel(version.name, version.version_no) }))
        onDone()
      }}
    />
  )
}
