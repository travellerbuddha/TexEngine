import { cn } from "../../lib/utils"
import { money } from "../lib/format"

/** Server amount (decimal string) rendered in the user's locale. Negative
 * values are marked for colour-blind users with a sign, not colour alone. */
export function Money({
  amount,
  currency,
  className,
  signed,
  muted,
}: {
  amount: string | null | undefined
  currency?: string | null
  className?: string
  signed?: boolean
  muted?: boolean
}) {
  const s = amount ?? ""
  const neg = s.trim().startsWith("-")
  const text = money(s, currency)
  return (
    <span
      className={cn(
        "tabular-nums whitespace-nowrap",
        signed && neg && "text-rose-700",
        signed && !neg && s && Number(s) !== 0 && "text-emerald-700",
        muted && "text-zinc-500",
        className,
      )}
    >
      {signed && !neg && s && Number(s) !== 0 ? "+" : ""}
      {text}
    </span>
  )
}
