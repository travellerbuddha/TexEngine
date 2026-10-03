// The hint on each exchange rate a reservation's price was converted with (G-56; LO-38). Pure, no React; unit tested
// with `node --test` (tests/unit/fx-hint.test.ts).
import type { FxRate } from "../../crs/lib/types"

/** The rate's source (provider, its own rate, the day), the provider a manual rate stood in for, its policy and what
 * it converted, joined by " · ". */
export function fxRateHint(r: FxRate, t: (key: string, params?: Record<string, string>) => string): string {
  return [
    r.provider && `${r.provider} ${r.provider_rate ?? ""} ${r.rate_date ?? ""}`,
    r.bridged_from && t("res.snap.fx_bridging", { provider: r.bridged_from }),
    r.policy_id,
    r.used_for.join(", "),
  ]
    .filter(Boolean)
    .join(" · ")
}
