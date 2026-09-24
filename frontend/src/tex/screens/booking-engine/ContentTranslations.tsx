import { useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { Languages } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { TEX_LANGS, useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Notice,
  PageHeader,
  Segmented,
  Skeleton,
  Textarea,
  useToast,
} from "../../ui"
import { BeNav } from "./BeNav"

interface Item {
  ref_doctype: string
  ref_name: string
  label: string
  fields: Record<string, string>
  translations: Record<string, Record<string, string>>
}

interface ItemsData {
  languages: string[]
  fields: Record<string, string[]>
  items: Item[]
}

type Kind = "hotel" | "rooms" | "rates" | "extras" | "policies"
const KIND_OF: Record<string, Kind> = {
  Property: "hotel",
  "Room Type": "rooms",
  "Rate Plan": "rates",
  "TEX Extra": "extras",
  "TEX Cancellation Policy": "policies",
  "TEX Payment Policy": "policies",
}
const KINDS: Kind[] = ["rooms", "rates", "extras", "policies", "hotel"]
// long texts get a textarea
const LONG = new Set(["description", "showcase_description", "tex_inclusions"])

const keyOf = (i: Item, field: string, lang: string) => `${i.ref_doctype}\u001f${i.ref_name}\u001f${field}\u001f${lang}`

/** Guest-facing hotel texts in every booking language (R-49). */
export default function ContentTranslations() {
  const { t } = useTexT()
  const { property, can } = useSession()
  const toast = useToast()
  const allowed = !!property && can("booking_site.edit")
  const q = useTexQuery<ItemsData>("content", "items", { property: property?.name }, [property?.name], allowed)
  const save = useTexMutation<{ property: string; rows: unknown[] }, { created: number; updated: number; deleted: number }>(
    "content",
    "save",
  )
  const [lang, setLang] = useState("de")
  // ?kind=rooms: opened from Booking Engine › Rooms (G-64)
  const [params] = useSearchParams()
  const [kind, setKind] = useState<Kind>(() => (KINDS.includes(params.get("kind") as Kind) ? (params.get("kind") as Kind) : "rooms"))
  const [edits, setEdits] = useState<Record<string, string>>({})

  const items = useMemo(() => (q.data?.items ?? []).filter((i) => KIND_OF[i.ref_doctype] === kind), [q.data, kind])
  const progress = useMemo(() => {
    let total = 0
    let done = 0
    for (const i of q.data?.items ?? [])
      for (const [f, base] of Object.entries(i.fields)) {
        if (!base) continue
        total += 1
        const k = keyOf(i, f, lang)
        const v = k in edits ? edits[k] : i.translations[lang]?.[f]
        if (v && v.trim()) done += 1
      }
    return { total, done }
  }, [q.data, edits, lang])
  const changed = Object.keys(edits).length

  const value = (i: Item, f: string) => {
    const k = keyOf(i, f, lang)
    return k in edits ? edits[k] : (i.translations[lang]?.[f] ?? "")
  }
  const setValue = (i: Item, f: string, v: string) => {
    const k = keyOf(i, f, lang)
    const original = i.translations[lang]?.[f] ?? ""
    setEdits((e) => {
      const next = { ...e }
      if (v === original) delete next[k]
      else next[k] = v
      return next
    })
  }
  const submit = async () => {
    if (!property) return
    const rows = Object.entries(edits).map(([k, text]) => {
      const [ref_doctype, ref_name, field, language] = k.split("\u001f")
      return { ref_doctype, ref_name, field, language, text }
    })
    try {
      const out = await save.run({ property: property.name, rows })
      toast.success(t("be.content.saved", { count: out.created + out.updated + out.deleted }))
      setEdits({})
      q.reload()
    } catch {
      /* shown inline */
    }
  }

  const langLabel = TEX_LANGS.find((l) => l.code === lang)?.label ?? lang
  return (
    <>
      <PageHeader
        title={t("be.content.title")}
        subtitle={property ? t("be.content.subtitle", { hotel: property.property_name }) : undefined}
        crumbs={[{ label: t("core.nav.booking_engine"), to: "/tex/booking-engine" }, { label: t("be.content.title") }]}
      />
      <BeNav />
      {!allowed ? (
        <Card>
          <EmptyState icon={<Languages className="size-5" />} title={t("core.error.permission")} description={t("be.content.no_access")} />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <div className="space-y-4 pb-20">
          <Notice tone="info">{t("be.content.hint")}</Notice>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="space-y-1">
              <p className="text-xs font-medium text-zinc-600">{t("be.content.language")}</p>
              <Segmented
                label={t("be.content.language")}
                value={lang}
                onChange={(v) => setLang(v)}
                options={TEX_LANGS.map((l) => ({ value: l.code, label: l.label }))}
              />
            </div>
            <p className="text-sm text-zinc-600" aria-live="polite">
              {t("be.content.progress", { done: progress.done, total: progress.total, language: langLabel })}
            </p>
          </div>
          <Segmented
            label={t("be.content.type")}
            value={kind}
            onChange={(v) => setKind(v)}
            options={KINDS.map((k) => ({ value: k, label: t(`be.content.kind.${k}`) }))}
          />
          {!q.data ? (
            <Card className="space-y-3 p-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </Card>
          ) : items.length === 0 ? (
            <Card>
              <EmptyState title={t("be.content.empty")} />
            </Card>
          ) : (
            items.map((i) => (
              <Card key={`${i.ref_doctype}-${i.ref_name}`}>
                <CardBody className="space-y-3">
                  <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-900">
                    {i.label}
                    {i.ref_doctype === "TEX Payment Policy" && <Badge tone="neutral">{t("be.content.payment_policy")}</Badge>}
                    {i.ref_doctype === "TEX Cancellation Policy" && <Badge tone="neutral">{t("be.content.cancellation_policy")}</Badge>}
                  </h2>
                  {Object.entries(i.fields).map(([f, base]) => {
                    const label = `${t(`be.content.field.${f}`)} · ${langLabel}`
                    const hint = base ? t("be.content.original", { text: base.length > 140 ? `${base.slice(0, 140)}…` : base }) : t("be.content.no_original")
                    return (
                      <Field key={f} label={label} hint={hint}>
                        {LONG.has(f) ? (
                          <Textarea rows={3} value={value(i, f)} placeholder={base} onChange={(e) => setValue(i, f, e.target.value)} maxLength={4000} />
                        ) : (
                          <Input value={value(i, f)} placeholder={base} onChange={(e) => setValue(i, f, e.target.value)} maxLength={400} />
                        )}
                      </Field>
                    )
                  })}
                </CardBody>
              </Card>
            ))
          )}
          {save.error && <Notice tone="danger">{save.error.message}</Notice>}
          {changed > 0 && (
            <div className="fixed inset-x-0 bottom-0 z-20 border-t border-zinc-200 bg-white/95 px-4 py-3 backdrop-blur lg:left-60">
              <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-zinc-700" aria-live="polite">
                  {t("be.content.unsaved", { count: changed })}
                </p>
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setEdits({})} disabled={save.pending}>
                    {t("be.content.discard")}
                  </Button>
                  <Button onClick={() => void submit()} loading={save.pending}>
                    {t("core.action.save")}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
