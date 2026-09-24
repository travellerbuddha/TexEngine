import { useNavigate } from "react-router-dom"
import { BedDouble, ImageOff, Languages } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { num } from "../../lib/format"
import { useSession } from "../../lib/session"
import { TEX_LANGS, useTexT } from "../../i18n"
import { Badge, Button, Card, CardBody, EmptyState, ErrorState, Notice, PageHeader, Skeleton, type Tone } from "../../ui"
import { BeNav } from "./BeNav"

interface RoomRow {
  name: string
  code: string | null
  room_type_name: string
  description: string | null
  image: string | null
  gallery: number
  bed_type: string | null
  beds: string | null
  size_sqm: string | null
  view: string | null
  amenities: string[]
  adults: number | null
  children: number | null
  max_occupants: number | null
  /** language → translated fields */
  translations: Record<string, string[]>
  /** live contracts selling the room */
  contracts: string[]
}

interface RoomsData {
  property: string
  languages: string[]
  fields: string[]
  rooms: RoomRow[]
}

const CONTRACTS_SHOWN = 6

const langLabel = (code: string) => TEX_LANGS.find((l) => l.code === code)?.label ?? code

/** The hotel's rooms as the booking engine shows them (R-28, R-35 Booking Engine › Rooms,
 * G-64): texts, picture, size, beds, occupancy, translations and the live contracts that
 * sell each room. Room texts are translated in Content; gaps are flagged, not guessed. */
export default function Rooms() {
  const { t } = useTexT()
  const navigate = useNavigate()
  const { property } = useSession()
  const q = useTexQuery<RoomsData>("lists", "rooms", { property: property?.name }, [property?.name], Boolean(property))
  const rooms = q.data?.rooms
  const gaps = (rooms ?? []).filter((r) => !r.image || !r.description || !r.contracts.length).length

  return (
    <>
      <PageHeader
        title={t("core.nav.sub.rooms")}
        subtitle={property ? t("be.rooms.subtitle", { hotel: property.property_name }) : undefined}
        crumbs={[{ label: t("core.nav.booking_engine"), to: "/tex/booking-engine" }, { label: t("core.nav.sub.rooms") }]}
        actions={
          <Button variant="secondary" icon={<Languages className="size-4" aria-hidden />} onClick={() => navigate("/tex/booking-engine/content?kind=rooms")}>
            {t("be.rooms.translate")}
          </Button>
        }
      />
      <BeNav />
      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !rooms ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-72 w-full" />
          ))}
        </div>
      ) : rooms.length === 0 ? (
        <Card>
          <EmptyState icon={<BedDouble className="size-5" />} title={t("be.rooms.none")} description={t("be.rooms.none_hint")} />
        </Card>
      ) : (
        <>
          <div className="mb-4 space-y-2">
            {gaps ? <Notice tone="warning">{t("be.rooms.gaps", { count: gaps })}</Notice> : <Notice tone="success">{t("be.rooms.complete")}</Notice>}
            <p className="text-xs text-zinc-600">{t("be.rooms.translations_hint")}</p>
          </div>
          <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label={t("core.nav.sub.rooms")}>
            {rooms.map((r) => (
              <li key={r.name}>
                <RoomCard room={r} fields={q.data?.fields ?? []} languages={q.data?.languages ?? []} />
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  )
}

function RoomCard({ room: r, fields, languages }: { room: RoomRow; fields: string[]; languages: string[] }) {
  const { t } = useTexT()
  const beds = [r.beds, r.bed_type].filter(Boolean).join(" · ")
  return (
    <Card className="flex h-full flex-col overflow-hidden">
      {r.image ? (
        <img src={r.image} alt={t("be.rooms.photo_of", { room: r.room_type_name })} className="aspect-[16/9] w-full bg-zinc-100 object-cover" loading="lazy" />
      ) : (
        <div className="flex aspect-[16/9] w-full flex-col items-center justify-center gap-1 bg-zinc-100 text-sm text-zinc-600">
          <ImageOff className="size-5" aria-hidden />
          {t("be.rooms.no_photo")}
        </div>
      )}
      <CardBody className="flex flex-1 flex-col gap-3">
        <div>
          <h2 className="flex flex-wrap items-baseline gap-x-2 text-base font-semibold text-zinc-950">
            {r.room_type_name}
            {r.code && <span className="font-mono text-xs font-normal text-zinc-500">{r.code}</span>}
          </h2>
          {r.gallery > 0 && <p className="text-xs text-zinc-500">{t("be.rooms.gallery", { count: r.gallery })}</p>}
        </div>
        {r.description ? (
          <p className="line-clamp-3 text-sm text-zinc-700">{r.description}</p>
        ) : (
          <p className="text-sm text-amber-800">{t("be.rooms.no_description")}</p>
        )}
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
          <dt className="text-zinc-500">{t("be.rooms.occupancy")}</dt>
          <dd className="text-zinc-900">
            {t("be.rooms.occupancy_value", { adults: r.adults ?? 0, children: r.children ?? 0 })}
            {r.max_occupants ? <span className="text-zinc-500"> · {t("be.rooms.max", { n: r.max_occupants })}</span> : null}
          </dd>
          <dt className="text-zinc-500">{t("be.rooms.size")}</dt>
          <dd className="text-zinc-900">{r.size_sqm ? `${num(r.size_sqm)} m²` : "—"}</dd>
          <dt className="text-zinc-500">{t("be.rooms.beds")}</dt>
          <dd className="text-zinc-900">{beds || "—"}</dd>
          <dt className="text-zinc-500">{t("be.rooms.view")}</dt>
          <dd className="text-zinc-900">{r.view || "—"}</dd>
        </dl>
        {r.amenities.length > 0 && (
          <ul className="flex flex-wrap gap-1" aria-label={t("be.rooms.amenities")}>
            {r.amenities.slice(0, 8).map((a) => (
              <li key={a}>
                <Badge tone="neutral">{a}</Badge>
              </li>
            ))}
            {r.amenities.length > 8 && <li className="text-xs text-zinc-500">+{r.amenities.length - 8}</li>}
          </ul>
        )}
        <div className="mt-auto space-y-2 border-t border-zinc-100 pt-3">
          <div>
            <p className="text-xs font-medium text-zinc-600">{t("be.rooms.sold_by")}</p>
            {r.contracts.length ? (
              <p className="mt-1 flex flex-wrap items-center gap-1">
                {r.contracts.slice(0, CONTRACTS_SHOWN).map((c) => (
                  <Badge key={c} tone="brand">
                    {c}
                  </Badge>
                ))}
                {r.contracts.length > CONTRACTS_SHOWN && (
                  <span className="text-xs text-zinc-600" title={r.contracts.slice(CONTRACTS_SHOWN).join(", ")}>
                    {t("be.rooms.more", { count: r.contracts.length - CONTRACTS_SHOWN })}
                  </span>
                )}
              </p>
            ) : (
              <p className="mt-1 text-sm text-amber-800">{t("be.rooms.not_sold")}</p>
            )}
          </div>
          <div>
            <p className="text-xs font-medium text-zinc-600">{t("be.rooms.translations")}</p>
            <ul className="mt-1 flex flex-wrap gap-1" aria-label={t("be.rooms.translations")}>
              {languages.map((lang) => {
                const done = r.translations[lang]?.length ?? 0
                const tone: Tone = done >= fields.length ? "success" : done ? "warning" : "neutral"
                return (
                  <li key={lang}>
                    <Badge tone={tone} title={langLabel(lang)}>
                      {lang.toUpperCase()} {done}/{fields.length}
                    </Badge>
                  </li>
                )
              })}
            </ul>
          </div>
        </div>
      </CardBody>
    </Card>
  )
}
