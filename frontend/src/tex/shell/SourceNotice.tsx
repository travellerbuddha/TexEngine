import { LICENSE, UPSTREAM, useSourceUrl } from "../../lib/source"
import { cn } from "../../lib/utils"
import { useTexT } from "../i18n"

// TEX Engine is a network service derived from Kamra PMS under AGPL-3.0: every user who
// interacts with it can get its source (section 13, ADR-060). The source URL is the running
// version's (lib/source: the served page, the API, else the build commit); the upstream and
// licence are fixed facts.

const linkCls = "underline decoration-zinc-300 underline-offset-2 hover:text-zinc-900 hover:decoration-zinc-500"

/** "Based on Kamra PMS · AGPL-3.0 · Source code": unobtrusive, always reachable. */
export function SourceNotice({ sourceUrl, className }: { sourceUrl?: string | null; className?: string }) {
  const { t } = useTexT()
  const source = useSourceUrl(sourceUrl)
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
      <a href={source} {...ext} className={linkCls}>
        {t("core.source.source")}
      </a>
    </p>
  )
}
