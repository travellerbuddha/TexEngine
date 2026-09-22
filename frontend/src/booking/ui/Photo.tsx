import { BedDouble, Building2 } from "lucide-react"
import { useId, useState } from "react"
import { safeImage } from "../lib/branding"

/** Hotel/room photo with a branded placeholder when there is no image (or it fails). */
export function Photo({
  src,
  alt,
  className = "",
  kind = "room",
  eager,
}: {
  src?: string | null
  alt: string
  className?: string
  kind?: "room" | "hotel"
  eager?: boolean
}) {
  const url = safeImage(src)
  const [failed, setFailed] = useState(false)
  const pid = useId()
  if (url && !failed)
    return (
      <img
        src={url}
        alt={alt}
        loading={eager ? "eager" : "lazy"}
        decoding="async"
        onError={() => setFailed(true)}
        className={`object-cover ${className}`}
      />
    )
  const Icon = kind === "hotel" ? Building2 : BedDouble
  return (
    <div
      className={`relative grid place-items-center overflow-hidden ${className}`}
      style={{
        background:
          "radial-gradient(120% 90% at 15% 10%, color-mix(in oklab, var(--bk-accent) 26%, white) 0%, transparent 60%), linear-gradient(150deg, color-mix(in oklab, var(--bk-primary) 22%, white), color-mix(in oklab, var(--bk-primary) 42%, white))",
      }}
      role="img"
      aria-label={alt}
    >
      <svg className="absolute inset-0 size-full opacity-[0.18]" aria-hidden>
        <defs>
          <pattern id={pid} width="18" height="18" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r="1.2" fill="white" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill={`url(#${pid})`} />
      </svg>
      <Icon className="relative size-10 text-white drop-shadow-sm" strokeWidth={1.4} aria-hidden />
    </div>
  )
}
