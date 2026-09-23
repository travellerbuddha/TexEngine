import type { ReactNode } from "react"
import { AlertTriangle, Lock, StickyNote, TrendingDown } from "lucide-react"
import { useTexT } from "../../i18n"
import { Kbd } from "../../ui"

/** Legend of the extras grid: every state has an icon or text, never colour alone (WCAG 1.4.1). */
export function ExtrasLegend() {
  const { t } = useTexT()
  const item = (swatch: ReactNode, label: string) => (
    <li className="flex items-center gap-1.5">
      {swatch}
      <span>{label}</span>
    </li>
  )
  return (
    <section aria-labelledby="inv-x-legend" className="mt-3 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-700">
      <h2 id="inv-x-legend" className="sr-only">
        {t("inventory.legend.title")}
      </h2>
      <ul className="flex flex-wrap gap-x-5 gap-y-1.5">
        {item(
          <span className="inline-flex h-5 items-center rounded px-1 font-semibold">
            3<span className="font-normal text-zinc-500">/10</span>
          </span>,
          t("inventory.extras.legend.sold_cap"),
        )}
        {item(<span className="inline-flex h-5 items-center rounded px-1 text-[10px] text-zinc-600">{t("inventory.extras.short.left", { n: 7 })}</span>, t("inventory.extras.legend.left"))}
        {item(
          <span className="inline-flex h-5 items-center rounded bg-rose-50 px-1 text-[10px] font-semibold text-rose-800">{t("inventory.extras.short.left", { n: 0 })}</span>,
          t("inventory.extras.legend.sold_out"),
        )}
        {item(
          <span className="inline-flex h-5 items-center gap-0.5 rounded bg-amber-50 px-1 text-[10px] font-semibold text-amber-900">
            <TrendingDown className="size-3" aria-hidden />
            {t("inventory.extras.short.left", { n: 1 })}
          </span>,
          t("inventory.extras.legend.low"),
        )}
        {item(
          <span className="inline-flex h-5 items-center gap-0.5 rounded bg-rose-100 px-1 text-[10px] font-semibold text-rose-900">
            <AlertTriangle className="size-3" aria-hidden />
            {t("inventory.extras.short.over")}
          </span>,
          t("inventory.extras.legend.over"),
        )}
        {item(
          <span className="inline-flex h-5 items-center gap-0.5 rounded bg-zinc-200/70 px-1 font-medium text-zinc-700">
            <Lock className="size-3" aria-hidden />
            {t("inventory.short.closed")}
          </span>,
          t("inventory.legend.closed"),
        )}
        {item(
          <span className="relative inline-block h-4 w-5 rounded-sm border border-zinc-300 bg-white">
            <span className="absolute top-0 right-0 size-0 border-t-[6px] border-l-[6px] border-t-tex-600 border-l-transparent" />
          </span>,
          t("inventory.extras.legend.override"),
        )}
        {item(<StickyNote className="size-3.5 text-zinc-500" aria-hidden />, t("inventory.extras.legend.note"))}
        <li className="flex items-center gap-1.5">
          <Kbd>←↑↓→</Kbd>
          <Kbd>Enter</Kbd>
          <span>{t("inventory.extras.legend.keys")}</span>
        </li>
      </ul>
    </section>
  )
}
