// Accessible single-series bar/column chart (SVG). The SVG is one labelled image
// with a text summary; the exact values always live in a table next to it, so the
// hover tooltip only enhances. Colours come from theme tokens (light + dark).
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { cn } from "../../../../lib/utils"
import { num } from "../../../lib/format"

export interface ChartDatum {
  key: string
  label: string
  /** Secondary line under the label (e.g. a date). */
  sublabel?: string
  value: number
  /** Formatted value shown in labels and the tooltip. */
  display: string
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    if (ref.current) setWidth(ref.current.getBoundingClientRect().width)
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

/** Clean tick step (1, 2, 5 × 10ⁿ) so axis labels read as round numbers. */
function niceTicks(max: number, count = 4, integer = true): number[] {
  if (!(max > 0)) return [0, 1]
  const raw = max / count
  const pow = 10 ** Math.floor(Math.log10(raw))
  const n = raw / pow
  let step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow
  if (integer) step = Math.max(1, Math.round(step))
  const ticks: number[] = []
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v)
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step)
  return ticks
}

/** Column with a 4px rounded data-end and a square baseline. */
function columnPath(x: number, y: number, w: number, h: number) {
  const r = Math.min(4, w / 2, h)
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

/** Horizontal bar: square at the baseline (left), rounded at the tip. */
function barPath(x: number, y: number, w: number, h: number) {
  const r = Math.min(4, h / 2, w)
  return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`
}

function clip(s: string, maxChars: number) {
  return s.length > maxChars ? `${s.slice(0, Math.max(1, maxChars - 1))}…` : s
}

interface Props {
  data: ChartDatum[]
  /** Accessible name + summary of what the chart shows (the table has the values). */
  summary: string
  orientation?: "vertical" | "horizontal"
  height?: number
  /** Integer axis (counts) vs decimal axis (amounts). */
  integer?: boolean
  /** Index to emphasise with a direct value label (vertical); defaults to the last point. */
  labelIndex?: number
  className?: string
  /** Dim while a refetch is running (keeps the frame). */
  stale?: boolean
}

export function BarChart({ data, summary, orientation = "vertical", height = 220, integer = true, labelIndex, className, stale }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [active, setActive] = useState<number | null>(null)
  const max = useMemo(() => Math.max(0, ...data.map((d) => d.value)), [data])
  const ticks = useMemo(() => niceTicks(max, 4, integer), [max, integer])
  const top = ticks[ticks.length - 1] || 1

  const horizontal = orientation === "horizontal"
  const rowH = 30
  const svgH = horizontal ? data.length * rowH + 8 : height
  const labelW = horizontal ? Math.min(170, Math.max(90, width * 0.34)) : 44
  const right = horizontal ? 72 : 12
  const topPad = horizontal ? 4 : 22
  const hasSub = !horizontal && data.some((d) => d.sublabel)
  const bottom = horizontal ? 4 : hasSub ? 38 : 24
  const plotW = Math.max(10, width - labelW - right)
  const plotH = Math.max(10, svgH - topPad - bottom)

  const band = horizontal ? rowH : plotW / Math.max(1, data.length)
  const thick = horizontal ? 18 : Math.min(24, Math.max(4, band * 0.62))
  const xEvery = horizontal ? 1 : Math.max(1, Math.ceil(data.length / Math.max(1, Math.floor(plotW / 56))))
  const emphasise = labelIndex ?? data.length - 1

  const act = active !== null ? data[active] : undefined
  let tipX = 0
  let tipY = 0
  if (act && active !== null) {
    if (horizontal) {
      tipX = labelW + (act.value / top) * plotW
      tipY = active * rowH + rowH / 2
    } else {
      tipX = labelW + band * active + band / 2
      tipY = topPad + plotH - (act.value / top) * plotH
    }
  }

  return (
    <div ref={ref} className={cn("relative w-full select-none", stale && "opacity-60 transition-opacity", className)}>
      {width > 0 && (
        <svg width={width} height={svgH} role="img" aria-label={summary} className="block overflow-visible">
          {horizontal ? (
            <>
              <line x1={labelW} x2={labelW} y1={0} y2={svgH - bottom} className="stroke-zinc-300" strokeWidth={1} />
              {data.map((d, i) => {
                const w = top ? (d.value / top) * plotW : 0
                const y = i * rowH + (rowH - thick) / 2
                const maxChars = Math.floor((labelW - 10) / 6.4)
                return (
                  <g key={d.key}>
                    <text x={labelW - 8} y={i * rowH + rowH / 2} dy="0.35em" textAnchor="end" className="fill-zinc-600 text-[11px]">
                      {clip(d.label, maxChars)}
                    </text>
                    {w > 0 && (
                      <path
                        d={barPath(labelW, y, Math.max(w, 2), thick)}
                        className={cn("transition-colors", active === i ? "fill-tex-700" : "fill-tex-500")}
                      />
                    )}
                    <text x={labelW + Math.max(w, 0) + 6} y={i * rowH + rowH / 2} dy="0.35em" className="fill-zinc-800 text-[11px] font-medium tabular-nums">
                      {d.display}
                    </text>
                    <rect
                      x={0}
                      y={i * rowH}
                      width={width}
                      height={rowH}
                      fill="transparent"
                      onPointerEnter={() => setActive(i)}
                      onPointerLeave={() => setActive(null)}
                    />
                  </g>
                )
              })}
            </>
          ) : (
            <>
              {ticks.map((tk) => {
                const y = topPad + plotH - (tk / top) * plotH
                return (
                  <g key={tk}>
                    <line x1={labelW} x2={width - right} y1={y} y2={y} className={tk === 0 ? "stroke-zinc-300" : "stroke-zinc-200"} strokeWidth={1} />
                    <text x={labelW - 6} y={y} dy="0.35em" textAnchor="end" className="fill-zinc-500 text-[10px] tabular-nums">
                      {num(tk)}
                    </text>
                  </g>
                )
              })}
              {data.map((d, i) => {
                const h = top ? (d.value / top) * plotH : 0
                const cx = labelW + band * i + band / 2
                const x = cx - thick / 2
                const y = topPad + plotH - h
                const showX = i % xEvery === 0 || i === data.length - 1
                return (
                  <g key={d.key}>
                    {h > 0 && (
                      <path
                        d={columnPath(x, y, thick, Math.max(h, 2))}
                        className={cn("transition-colors", active === i ? "fill-tex-700" : "fill-tex-500")}
                      />
                    )}
                    {i === emphasise && (
                      <text x={cx} y={y - 6} textAnchor="middle" className="fill-zinc-800 text-[11px] font-semibold tabular-nums">
                        {d.display}
                      </text>
                    )}
                    {showX && (
                      <text x={cx} y={topPad + plotH + 14} textAnchor="middle" className="fill-zinc-600 text-[10px]">
                        {clip(d.label, Math.max(4, Math.floor((band * xEvery) / 6)))}
                        {d.sublabel && (
                          <tspan x={cx} dy="1.25em" className="fill-zinc-400">
                            {clip(d.sublabel, Math.max(4, Math.floor((band * xEvery) / 6)))}
                          </tspan>
                        )}
                      </text>
                    )}
                    <rect
                      x={labelW + band * i}
                      y={topPad}
                      width={band}
                      height={plotH}
                      fill="transparent"
                      onPointerEnter={() => setActive(i)}
                      onPointerLeave={() => setActive(null)}
                    />
                  </g>
                )
              })}
            </>
          )}
        </svg>
      )}
      {act && (
        <div
          aria-hidden
          className="pointer-events-none absolute z-10 min-w-28 -translate-x-1/2 -translate-y-full rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs shadow-tex-pop"
          style={{ left: Math.min(Math.max(tipX, 60), Math.max(60, width - 60)), top: Math.max(0, tipY - 8) }}
        >
          <p className="font-semibold text-zinc-950 tabular-nums">{act.display}</p>
          <p className="text-zinc-600">{act.label}</p>
          {act.sublabel && <p className="text-zinc-500">{act.sublabel}</p>}
        </div>
      )}
    </div>
  )
}
