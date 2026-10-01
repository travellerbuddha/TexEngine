import { useState } from "react"
import { Download, Plus } from "lucide-react"
import { tex, TexApiError, useTexQuery, useTexMutation } from "../../../lib/api"
import { useSession, type TexProperty } from "../../../lib/session"
import { date as fmtDate, dateTime } from "../../../lib/format"
import { useSiteToday } from "../../../lib/siteDay"
import { useTexT } from "../../../i18n"
import { Button, Card, CardBody, CardHeader, DataTable, DecimalInput, EmptyState, ErrorState, Field, FormGrid, InlineError, Input, Notice, PageHeader, Segmented, Select, Toolbar, useToast } from "../../../ui"
import { RatesNav } from "../components/RatesNav"
import { enumLabel } from "../lib/options"
import { decText } from "../lib/util"

interface FxRate {
  name: string
  provider: string
  base_currency: string
  quote_currency: string
  rate_type: string
  rate: number | string
  rate_date: string
  fetched_at: string | null
  /** A manual rate's hotel (blank = every hotel) and who entered it; provider rows have neither. */
  property?: string | null
  source_ref?: string | null
}

type Provider = "TCMB" | "ECB" | "MANUAL"

/** Provider FX rates (TCMB / ECB / manual). A rate always reads 1 base = rate quote. */
export default function FxRates() {
  const { t } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  const [provider, setProvider] = useState<Provider>("TCMB")
  const [days, setDays] = useState("14")
  const [base, setBase] = useState("")
  const q = useTexQuery<FxRate[]>("policies", "fx_rates", { provider, days: Number(days), base: base || undefined }, [provider, days, base])
  const { can } = useSession()
  // provider rates are shared by every hotel: platform administrators fetch them. A manual rate is for one hotel
  // (fx.manual_rate there) or for every hotel (platform administrators): D-4, O-12
  const canFetch = boot.user.platform_admin
  const manualHotels = boot.properties.filter((p) => can("fx.manual_rate", p.name))
  const canManual = canFetch || manualHotels.length > 0
  const hotelName = (name?: string | null) => (name ? (boot.properties.find((p) => p.name === name)?.property_name ?? name) : t("rates.fx.hotel_all"))
  const [fetching, setFetching] = useState<string | null>(null)
  const [fetchErr, setFetchErr] = useState<TexApiError>()
  const [fetchResult, setFetchResult] = useState<string>()

  const fetchNow = async (p: "TCMB" | "ECB") => {
    setFetching(p)
    setFetchErr(undefined)
    setFetchResult(undefined)
    try {
      const r = await tex<unknown>("policies", "fetch_fx", { provider: p }, { post: true })
      setFetchResult(summarise(r, t))
      toast.success(t("rates.fx.fetched", { provider: p }))
      if (p === provider) q.reload()
      else setProvider(p)
    } catch (e) {
      setFetchErr(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
    } finally {
      setFetching(null)
    }
  }

  return (
    <>
      <RatesNav />
      <PageHeader
        title={t("rates.fx.title")}
        subtitle={t("rates.fx.subtitle")}
        actions={
          canFetch && (
            <>
              <Button variant="secondary" icon={<Download className="size-4" aria-hidden />} loading={fetching === "TCMB"} disabled={Boolean(fetching)} onClick={() => void fetchNow("TCMB")}>
                {t("rates.fx.fetch", { provider: "TCMB" })}
              </Button>
              <Button variant="secondary" icon={<Download className="size-4" aria-hidden />} loading={fetching === "ECB"} disabled={Boolean(fetching)} onClick={() => void fetchNow("ECB")}>
                {t("rates.fx.fetch", { provider: "ECB" })}
              </Button>
            </>
          )
        }
      />
      {fetchErr && (
        <div className="mb-4">
          <InlineError error={fetchErr} />
        </div>
      )}
      {fetchResult && (
        <div className="mb-4">
          <Notice tone="success">{fetchResult}</Notice>
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Toolbar>
            <Segmented<Provider>
              label={t("rates.f.provider")}
              value={provider}
              onChange={setProvider}
              options={[
                { value: "TCMB", label: "TCMB" },
                { value: "ECB", label: "ECB" },
                { value: "MANUAL", label: t("rates.fx_provider.MANUAL") },
              ]}
            />
            <Field label={t("rates.fx.days")} className="w-40">
              <Select value={days} onChange={(e) => setDays(e.target.value)} options={["7", "14", "30", "90"].map((d) => ({ value: d, label: t("rates.fx.last_days", { count: Number(d) }) }))} />
            </Field>
            <Field label={t("rates.fx.base")} className="w-32">
              <Select value={base} onChange={(e) => setBase(e.target.value)} options={boot.currencies.map((c) => ({ value: c, label: c }))} placeholder={t("core.label.all")} />
            </Field>
          </Toolbar>
          <Card>
            {q.error ? (
              <ErrorState error={q.error} onRetry={q.reload} />
            ) : (
              <DataTable<FxRate>
                caption={t("rates.fx.title")}
                rows={q.data}
                loading={q.loading}
                rowKey={(r) => r.name}
                dense
                initialSort={{ key: "rate_date", dir: "desc" }}
                empty={<EmptyState title={t("rates.fx.none")} description={canFetch && provider !== "MANUAL" ? t("rates.fx.none_hint") : undefined} />}
                columns={[
                  { key: "rate_date", header: t("rates.fx.date"), sortValue: (r) => r.rate_date, cell: (r) => <span className="whitespace-nowrap">{fmtDate(r.rate_date)}</span> },
                  { key: "pair", header: t("rates.f.pair"), sortValue: (r) => r.base_currency + r.quote_currency, cell: (r) => <span className="font-medium">{r.base_currency}/{r.quote_currency}</span> },
                  { key: "rate", header: t("rates.fx.rate"), align: "right", cell: (r) => <span className="font-medium tabular-nums">{decText(r.rate, 0)}</span> },
                  { key: "rate_type", header: t("rates.f.rate_type"), hideBelow: "md", cell: (r) => enumLabel(t, "rate_type", r.rate_type) },
                  { key: "fetched_at", header: t("rates.fx.fetched_at"), hideBelow: "lg", cell: (r) => (r.fetched_at ? dateTime(r.fetched_at) : "—") },
                  ...(provider === "MANUAL"
                    ? [
                        { key: "property", header: t("rates.fx.hotel"), hideBelow: "md" as const, cell: (r: FxRate) => hotelName(r.property) },
                        { key: "source_ref", header: t("rates.fx.entered_by"), hideBelow: "lg" as const, cell: (r: FxRate) => r.source_ref ?? "—" },
                      ]
                    : []),
                ]}
              />
            )}
          </Card>
        </div>
        <div className="self-start">
          {canManual ? (
            <ManualRate hotels={manualHotels} everyHotel={canFetch} onSaved={() => (provider === "MANUAL" ? q.reload() : setProvider("MANUAL"))} />
          ) : (
            <Notice tone="info">{t("rates.fx.read_only")}</Notice>
          )}
        </div>
      </div>
    </>
  )
}

function summarise(r: unknown, t: (k: string, p?: Record<string, string | number>) => string): string {
  if (r && typeof r === "object") {
    const o = r as Record<string, unknown>
    if (typeof o.added === "number")
      return t("rates.fx.fetch_result", { count: o.added, seen: Number(o.seen ?? 0), date: o.rate_date ? fmtDate(String(o.rate_date)) : "—" })
    return Object.entries(o)
      .filter(([, v]) => typeof v !== "object")
      .map(([k, v]) => `${k}: ${String(v)}`)
      .join(" · ")
  }
  return String(r ?? "")
}

function ManualRate({ hotels, everyHotel, onSaved }: { hotels: TexProperty[]; everyHotel: boolean; onSaved: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  const add = useTexMutation<{ base_currency: string; quote_currency: string; rate: string; rate_date: string; property?: string; reason?: string }>("policies", "add_manual_rate")
  const { property: selected } = useSession()
  // the hotel the rate is for: the selected one when the caller may enter rates there; "" = every hotel (platform administrators)
  const [hotel, setHotel] = useState<string>(() => (hotels.some((h) => h.name === selected?.name) ? (selected?.name ?? "") : (hotels[0]?.name ?? "")))
  const [reason, setReason] = useState("")
  // rate date null = the site's today (G-91), which follows the site's midnight until one is picked
  const today = useSiteToday()
  const [f, setF] = useState<{ base_currency: string; quote_currency: string; rate: string; rate_date: string | null }>({ base_currency: "EUR", quote_currency: "TRY", rate: "", rate_date: null })
  const rateDate = f.rate_date ?? today
  const ok = f.base_currency && f.quote_currency && f.base_currency !== f.quote_currency && /^\d+(\.\d+)?$/.test(f.rate) && f.rate.replace(/[0.]/g, "") !== "" && rateDate
  const ccy = boot.currencies.map((c) => ({ value: c, label: c }))
  return (
    <Card>
      <CardHeader title={t("rates.fx.manual_title")} description={t("rates.fx.manual_hint")} />
      <CardBody>
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!ok) return
            try {
              await add.run({ ...f, rate_date: rateDate, property: hotel || undefined, reason: reason.trim() || undefined })
              toast.success(t("rates.fx.manual_saved", { pair: `${f.base_currency}/${f.quote_currency}` }))
              setF((x) => ({ ...x, rate: "" }))
              setReason("")
              onSaved()
            } catch {
              /* inline */
            }
          }}
        >
          <FormGrid cols={2}>
            <Field label={t("rates.fx.base")} required>
              <Select value={f.base_currency} onChange={(e) => setF({ ...f, base_currency: e.target.value })} options={ccy} />
            </Field>
            <Field label={t("rates.fx.quote")} required error={f.base_currency === f.quote_currency ? t("rates.fx.same_ccy") : undefined}>
              <Select value={f.quote_currency} onChange={(e) => setF({ ...f, quote_currency: e.target.value })} options={ccy} />
            </Field>
          </FormGrid>
          <Field label={t("rates.fx.rate")} required hint={f.rate ? t("rates.fx.reads", { base: f.base_currency, rate: decText(f.rate, 0), quote: f.quote_currency }) : t("rates.fx.rate_hint")}>
            <DecimalInput value={f.rate} onValueChange={(v) => setF({ ...f, rate: v })} decimals={9} suffix={f.quote_currency} />
          </Field>
          <Field label={t("rates.fx.date")} required>
            <Input type="date" value={rateDate} onChange={(e) => setF({ ...f, rate_date: e.target.value })} />
          </Field>
          <Field label={t("rates.fx.hotel")} required>
            <Select
              value={hotel}
              onChange={(e) => setHotel(e.target.value)}
              options={[...(everyHotel ? [{ value: "", label: t("rates.fx.hotel_all") }] : []), ...hotels.map((h) => ({ value: h.name, label: h.property_name }))]}
            />
          </Field>
          <Field label={t("rates.fx.reason")}>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
          </Field>
          <InlineError error={add.error} />
          <Button type="submit" loading={add.pending} disabled={!ok} icon={<Plus className="size-4" aria-hidden />}>
            {t("rates.fx.add_manual")}
          </Button>
        </form>
      </CardBody>
    </Card>
  )
}
