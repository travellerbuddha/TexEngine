// Live preview of a booking site built only from the safe branding tokens.
// Colours are applied only when they are valid #RRGGBB, fonts only from the
// allow-list and images only through <img> with a vetted URL — the preview
// never interprets free CSS, mirroring what the guest pages may do.
import { useState, type CSSProperties, type ReactNode } from "react"
import { BedDouble, CalendarDays, Search, Users } from "lucide-react"
import { useTexT } from "../../i18n"
import { Segmented } from "../../ui"
import { cn } from "../../../lib/utils"
import { FONT_STACK, HEX, RADIUS_PX, csv, onColor, parseTexts, safeImageUrl, type Site } from "./site"

function safeHex(v: string, fallback: string) {
  return HEX.test(v) ? v : fallback
}

export function BrandPreview({ site }: { site: Site }) {
  const { t } = useTexT()
  const [device, setDevice] = useState<"desktop" | "mobile">(() => (typeof window !== "undefined" && window.innerWidth < 640 ? "mobile" : "desktop"))
  const primary = safeHex(site.primary_color, "#0B3B5B")
  const accent = safeHex(site.accent_color, "#C8963E")
  const bg = safeHex(site.background_color, "#F7F7F5")
  const r = RADIUS_PX[site.radius] ?? 8
  const cr = RADIUS_PX[site.card_radius] ?? 12
  const font = FONT_STACK[site.font_family] ?? FONT_STACK.Inter
  const logo = safeImageUrl(site.logo)
  const hero = safeImageUrl(site.hero_image)
  const lang = csv(site.languages).includes(site.default_language) ? site.default_language : (csv(site.languages)[0] ?? "en")
  const texts = parseTexts(site.custom_texts)
  const langTexts = typeof texts[lang] === "object" ? (texts[lang] as Record<string, string>) : {}
  const headline = langTexts.headline || site.site_name || t("be.preview.sample_name")
  const tagline = langTexts.tagline || t("be.preview.sample_tagline")
  const cta = langTexts.search_button || t("be.preview.search")
  const mobile = device === "mobile"

  const button = (label: string, extra?: string, icon = true) => {
    const style: CSSProperties =
      site.button_style === "outline"
        ? { border: `1.5px solid ${primary}`, color: primary, background: "transparent", borderRadius: r }
        : { background: primary, color: onColor(primary), borderRadius: site.button_style === "pill" ? 999 : r }
    return (
      <span className={cn("inline-flex items-center justify-center gap-1.5 px-3.5 py-2 text-[12px] font-semibold whitespace-nowrap", extra)} style={style}>
        {icon && <Search className="size-3.5" aria-hidden />}
        {label}
      </span>
    )
  }

  const field = (icon: ReactNode, label: string) => (
    <span className="flex min-w-0 flex-1 items-center gap-1.5 border border-black/10 bg-[#ffffff] px-2.5 py-2 text-[11px] text-[#52525b]" style={{ borderRadius: r }}>
      {icon}
      <span className="truncate">{label}</span>
    </span>
  )

  const searchBar = (
    <div
      className={cn(
        "flex gap-2",
        mobile ? "flex-col" : "flex-row items-stretch",
        site.search_style === "card" && "bg-[#ffffff] p-3 shadow-lg",
        site.search_style === "overlay" && "bg-[rgb(255_255_255/0.82)] p-2.5 backdrop-blur",
      )}
      style={site.search_style !== "inline" ? { borderRadius: cr } : undefined}
    >
      {field(<CalendarDays className="size-3.5 shrink-0" aria-hidden />, t("be.preview.dates"))}
      {field(<Users className="size-3.5 shrink-0" aria-hidden />, t("be.preview.guests"))}
      {button(cta)}
    </div>
  )

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-zinc-900">{t("be.preview.title")}</p>
        <Segmented<"desktop" | "mobile">
          size="sm"
          label={t("be.preview.device")}
          value={device}
          onChange={setDevice}
          options={[
            { value: "desktop", label: t("be.preview.desktop") },
            { value: "mobile", label: t("be.preview.mobile") },
          ]}
        />
      </div>
      <div className="rounded-xl border border-zinc-200 bg-zinc-100 p-2">
        <div
          role="img"
          aria-label={t("be.preview.aria", { name: site.site_name || t("be.preview.sample_name") })}
          className={cn("mx-auto overflow-hidden rounded-lg shadow-sm transition-[max-width]", mobile ? "max-w-[300px]" : "max-w-full")}
          style={{ background: bg, fontFamily: font, color: "#1f2328" }}
        >
          {/* header */}
          <div
            className={cn(
              "flex items-center gap-3 border-b border-black/5 bg-[#ffffff] px-4 py-2.5",
              site.header_layout === "center" && "justify-center",
              site.header_layout === "split" && "justify-between",
            )}
          >
            <span className="flex min-w-0 items-center gap-2">
              {logo ? (
                <img src={logo} alt="" className="h-6 w-auto max-w-[120px] object-contain" />
              ) : (
                <span className="grid size-6 shrink-0 place-items-center text-[11px] font-bold" style={{ background: primary, color: onColor(primary), borderRadius: r }}>
                  {(site.site_name || "T").slice(0, 1).toUpperCase()}
                </span>
              )}
              <span className="truncate text-[13px] font-semibold">{site.site_name || t("be.preview.sample_name")}</span>
            </span>
            {site.header_layout === "split" && !mobile && (
              <span className="flex gap-3 text-[11px] text-[#52525b]">
                <span>{t("be.preview.rooms")}</span>
                <span>{t("be.preview.offers")}</span>
                <span style={{ color: accent }} className="font-semibold">
                  {lang.toUpperCase()}
                </span>
              </span>
            )}
          </div>
          {/* hero + search */}
          <div className="relative">
            <div className={cn("relative overflow-hidden", mobile ? "h-40" : "h-44")} style={{ background: `linear-gradient(135deg, ${primary}, ${accent})` }}>
              {hero && <img src={hero} alt="" className="absolute inset-0 size-full object-cover" />}
              <div className="absolute inset-0 bg-black/30" aria-hidden />
              <div className={cn("relative flex h-full flex-col justify-center px-5 text-[#ffffff]", site.header_layout === "center" && "items-center text-center")}>
                <p className={cn("leading-tight font-semibold", mobile ? "text-[17px]" : "text-[22px]")}>{headline}</p>
                <p className="mt-1 text-[12px] opacity-90">{tagline}</p>
              </div>
              {site.search_style === "overlay" && <div className="absolute inset-x-4 bottom-3">{searchBar}</div>}
            </div>
            {site.search_style === "card" && <div className="relative -mt-8 px-4">{searchBar}</div>}
            {site.search_style === "inline" && <div className="border-b border-black/5 bg-[#ffffff] px-4 py-3">{searchBar}</div>}
          </div>
          {/* room card */}
          <div className={cn("grid gap-3 p-4", mobile ? "grid-cols-1" : "grid-cols-2")}>
            {[0, 1].slice(0, mobile ? 1 : 2).map((i) => (
              <div key={i} className="overflow-hidden bg-[#ffffff] shadow-sm" style={{ borderRadius: cr }}>
                <div className="grid h-16 place-items-center" style={{ background: `${primary}1a`, color: primary }}>
                  <BedDouble className="size-6" aria-hidden />
                </div>
                <div className="space-y-2 p-3">
                  <p className="text-[12px] font-semibold">{i === 0 ? t("be.preview.room_a") : t("be.preview.room_b")}</p>
                  <span className="inline-block px-1.5 py-0.5 text-[10px] font-semibold" style={{ background: `${accent}26`, color: "#1f2328", borderRadius: r }}>
                    {t("be.preview.badge")}
                  </span>
                  <div className="flex items-center justify-between gap-2">
                    <span className="h-2.5 w-16 rounded bg-[#e4e4e7]" aria-hidden />
                    {button(t("be.preview.select"), "py-1.5", false)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="text-xs text-zinc-500">{t("be.preview.note")}</p>
    </div>
  )
}
