import { cn } from "../../lib/utils"
import { useTexT } from "../i18n"

// TEX Engine is a network service derived from Kamra PMS under AGPL-3.0: every user who
// interacts with it can get its source (section 13, ADR-060). The source URL comes from the
// server (kamra.tex.entry.source_url); the upstream and licence are fixed facts.
export const UPSTREAM = { name: "Kamra PMS", url: "https://github.com/Kamra-PMS/kamra-pms" }
export const LICENSE = { name: "AGPL-3.0", url: "https://www.gnu.org/licenses/agpl-3.0.html" }

const linkCls = "underline decoration-zinc-300 underline-offset-2 hover:text-zinc-900 hover:decoration-zinc-500"

/** "Based on Kamra PMS · AGPL-3.0 · Source code": unobtrusive, always reachable. */
export function SourceNotice({ sourceUrl, className }: { sourceUrl?: string | null; className?: string }) {
  const { t } = useTexT()
  const [before, after = ""] = t("core.source.based_on", { name: "\u0000" }).split("\u0000")
  const ext = { target: "_blank", rel: "noopener noreferrer" } as const
  return (
    <p className={cn("text-xs leading-relaxed text-zinc-500", className)} data-testid="tex-source-notice">
      {before}
      <a href={UPSTREAM.url} {...ext} className={linkCls}>
        {UPSTREAM.name}
      </a>
      {after}
      <span aria-hidden> · </span>
      <a href={LICENSE.url} {...ext} className={linkCls} title={t("core.source.license_hint")}>
        {LICENSE.name}
      </a>
      <span aria-hidden> · </span>
      <a href={sourceUrl || "https://github.com/travellerbuddha/TexEngine"} {...ext} className={linkCls}>
        {t("core.source.source")}
      </a>
    </p>
  )
}
