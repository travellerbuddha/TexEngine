import type { ReactNode } from "react"
import { ArrowDownToLine, ArrowUpFromLine, Ban, Lock, PencilLine, Tag } from "lucide-react"
import { useTexT } from "../../i18n"
import { Kbd } from "../../ui"

/** Grid legend: every state has an icon or text, never colour alone (WCAG 1.4.1). */
export function Legend() {
  const { t } = useTexT()
  const item = (swatch: ReactNode, label: string) => (
    <li className="flex items-center gap-1.5">
      {swatch}
      <span>{label}</span>
    </li>
  )
  return (
    <section aria-labelledby="inv-legend" className="mt-3 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-700">
      <h2 id="inv-legend" className="sr-only">
        {t("inventory.legend.title")}
      </h2>
      <ul className="flex flex-wrap gap-x-5 gap-y-1.5">
        {item(
          <span className="inline-flex h-5 items-center gap-0.5 rounded bg-rose-50 px-1 font-semibold text-rose-800">
            <Ban className="size-3" aria-hidden />
            {t("inventory.short.stop")}
          </span>,
          t("inventory.legend.stop"),
        )}
        {item(
          <span className="inline-flex h-5 items-center rounded bg-rose-50 px-1 font-semibold text-rose-800">0/12</span>,
          t("inventory.legend.sold_out"),
        )}
        {item(
          <span className="inline-flex h-5 items-center rounded bg-amber-50 px-1 font-semibold text-amber-900">2/12</span>,
          t("inventory.legend.low"),
        )}
        {item(
          <span className="inline-flex h-5 items-center gap-0.5 rounded bg-zinc-200/70 px-1 font-medium text-zinc-700">
            <Lock className="size-3" aria-hidden />
            {t("inventory.short.closed")}
          </span>,
          t("inventory.legend.closed"),
        )}
        {item(
          <span className="inline-flex h-5 items-center gap-1 rounded bg-amber-50 px-1 font-semibold text-amber-900">
            <ArrowDownToLine className="size-3" aria-hidden />
            CTA
            <ArrowUpFromLine className="size-3" aria-hidden />
            CTD
          </span>,
          t("inventory.legend.cta_ctd"),
        )}
        {item(
          <span className="inline-flex h-5 items-center gap-0.5 font-semibold text-amber-800">
            <PencilLine className="size-3" aria-hidden />
            99.00
          </span>,
          t("inventory.legend.draft"),
        )}
        {item(<Tag className="size-3.5 text-emerald-700" aria-hidden />, t("inventory.legend.promo"))}
        {item(
          <span className="relative inline-block h-4 w-5 rounded-sm border border-zinc-300 bg-white">
            <span className="absolute top-0 right-0 size-0 border-t-[6px] border-l-[6px] border-t-tex-600 border-l-transparent" />
          </span>,
          t("inventory.legend.own"),
        )}
        {item(<span className="font-semibold">2/7</span>, t("inventory.legend.los"))}
        <li className="flex items-center gap-1.5">
          <Kbd>←↑↓→</Kbd>
          <Kbd>Enter</Kbd>
          <span>{t("inventory.legend.keys")}</span>
        </li>
      </ul>
    </section>
  )
}
