import { useI18n } from "../i18n"
import { LICENSE, useSourceUrl } from "../../lib/source"

// Guests use TEX Engine too, so they are offered its source (AGPL-3.0 section 13, ADR-060
// review): "Booking engine by TEX Engine · AGPL-3.0 · Source code" on every guest page (the site,
// its booking, manage and payment pages, the error pages, the widget's modal). No site setting
// removes it. The address is the running version's (lib/source).
const ext = { target: "_blank", rel: "noopener noreferrer" } as const
const linkCls = "underline underline-offset-2 hover:text-ink"

export function SourceLine({ className }: { className?: string }) {
  const { t } = useI18n()
  const source = useSourceUrl()
  return (
    <p className={className ?? "text-xs text-muted"} data-testid="tex-source-notice">
      {t("footer.poweredBy")}
      <span aria-hidden> · </span>
      <a href={LICENSE.url} {...ext} className={linkCls} title={t("footer.sourceHint")}>
        {LICENSE.name}
      </a>
      <span aria-hidden> · </span>
      <a href={source} {...ext} className={linkCls}>
        {t("footer.source")}
      </a>
    </p>
  )
}
