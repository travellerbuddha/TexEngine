// White-label branding (R-32, ADR-012): only safe tokens are applied — validated hex
// colours, a font from an allow-list, radius steps and a button style. There is no
// way to inject CSS or scripts. Colours are adjusted where needed so text keeps
// WCAG AA contrast whatever the hotel picks.
import type { Branding } from "../types"

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i

export const DEFAULT_BRAND = { primary: "#1C3FA8", accent: "#E0A526", background: "#F7F7F5" }

type RGB = [number, number, number]

export function parseHex(v: string | null | undefined): RGB | null {
  if (!v || !HEX.test(v.trim())) return null
  let h = v.trim().slice(1)
  if (h.length === 3) h = h.split("").map((c) => c + c).join("")
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB
}

function toHex([r, g, b]: RGB) {
  return "#" + [r, g, b].map((c) => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, "0")).join("")
}

function luminance([r, g, b]: RGB) {
  const ch = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)
}

export function contrast(a: RGB, b: RGB) {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m)
  return (x + 0.05) / (y + 0.05)
}

const WHITE: RGB = [255, 255, 255]
const INK: RGB = [22, 24, 29]

function mix(a: RGB, b: RGB, t: number): RGB {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

/** Darken (or lighten) `c` towards `toward` until it reaches `ratio` against `bg`. */
function ensureContrast(c: RGB, bg: RGB, ratio: number, toward: RGB = INK): RGB {
  let out = c
  for (let i = 0; i <= 20 && contrast(out, bg) < ratio; i++) out = mix(c, toward, i / 20)
  return out
}

/** Best text colour (near-black or white) on a background. */
function onColor(bg: RGB): RGB {
  return contrast(WHITE, bg) >= contrast(INK, bg) ? WHITE : INK
}

const RADIUS: Record<string, string> = { none: "0px", sm: "4px", md: "8px", lg: "12px", xl: "18px" }
const CARD_RADIUS: Record<string, string> = { none: "0px", sm: "6px", md: "10px", lg: "16px", xl: "24px" }

/** Font allow-list (TEX Booking Site.font_family). Web fonts come from Bunny Fonts,
 * a GDPR-friendly Google Fonts mirror that sets no cookies and keeps no IP logs. */
export const FONTS: Record<string, { stack: string; css?: string }> = {
  Inter: { stack: '"Inter", ui-sans-serif, system-ui, sans-serif', css: "inter:400,500,600,700" },
  "DM Sans": { stack: '"DM Sans", ui-sans-serif, system-ui, sans-serif', css: "dm-sans:400,500,600,700" },
  "Nunito Sans": { stack: '"Nunito Sans", ui-sans-serif, system-ui, sans-serif', css: "nunito-sans:400,600,700" },
  "Source Sans 3": { stack: '"Source Sans 3", ui-sans-serif, system-ui, sans-serif', css: "source-sans-3:400,600,700" },
  Lora: { stack: '"Lora", ui-serif, Georgia, serif', css: "lora:400,500,600,700" },
  "Playfair Display": { stack: '"Playfair Display", ui-serif, Georgia, serif', css: "playfair-display:400,600,700" },
  System: { stack: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' },
}

const SERIF_HEADINGS = new Set(["Lora", "Playfair Display"])

function loadFont(name: string) {
  const f = FONTS[name]
  if (!f?.css) return
  const id = "tex-font-" + name.replace(/\s+/g, "-").toLowerCase()
  if (document.getElementById(id)) return
  const link = document.createElement("link")
  link.id = id
  link.rel = "stylesheet"
  link.href = `https://fonts.bunny.net/css?family=${f.css}&display=swap`
  document.head.appendChild(link)
}

export interface Theme {
  vars: Record<string, string>
  buttonStyle: "solid" | "outline" | "pill"
  header: "left" | "center" | "split"
  searchStyle: "inline" | "card" | "overlay"
}

export function themeFrom(b: Branding | null | undefined): Theme {
  const primary = parseHex(b?.primary) ?? parseHex(DEFAULT_BRAND.primary)!
  const accent = parseHex(b?.accent) ?? parseHex(DEFAULT_BRAND.accent)!
  const bg = parseHex(b?.background) ?? parseHex(DEFAULT_BRAND.background)!
  // the page background must stay light enough for dark body text
  const canvas = contrast(INK, bg) >= 7 ? bg : ensureContrast(bg, INK, 7, WHITE)
  const fontName = b?.font && FONTS[b.font] ? b.font : "Inter"
  const primaryInk = ensureContrast(primary, WHITE, 4.6)
  const accentInk = ensureContrast(accent, WHITE, 4.6)
  const vars: Record<string, string> = {
    "--bk-primary": toHex(primary),
    "--bk-on-primary": toHex(onColor(primary)),
    "--bk-primary-ink": toHex(primaryInk),
    "--bk-accent": toHex(accent),
    "--bk-on-accent": toHex(onColor(accent)),
    "--bk-accent-ink": toHex(accentInk),
    "--bk-canvas": toHex(canvas),
    "--bk-font": FONTS[fontName].stack,
    "--bk-heading-font": FONTS[fontName].stack,
    "--bk-heading-weight": SERIF_HEADINGS.has(fontName) ? "600" : "650",
    "--bk-radius": RADIUS[b?.radius ?? "md"] ?? RADIUS.md,
    "--bk-card-radius": CARD_RADIUS[b?.card_radius ?? "lg"] ?? CARD_RADIUS.lg,
  }
  const buttonStyle = (["solid", "outline", "pill"].includes(b?.button_style ?? "") ? b!.button_style : "solid") as Theme["buttonStyle"]
  vars["--bk-button-radius"] = buttonStyle === "pill" ? "999px" : vars["--bk-radius"]
  return {
    vars,
    buttonStyle,
    header: (["left", "center", "split"].includes(b?.header ?? "") ? b!.header : "left") as Theme["header"],
    searchStyle: (["inline", "card", "overlay"].includes(b?.search_style ?? "") ? b!.search_style : "card") as Theme["searchStyle"],
  }
}

export function applyTheme(theme: Theme, fontName?: string | null) {
  const root = document.documentElement
  for (const [k, v] of Object.entries(theme.vars)) root.style.setProperty(k, v)
  root.dataset.buttons = theme.buttonStyle
  if (fontName && FONTS[fontName]) loadFont(fontName)
}

/** Only same-origin paths or https URLs are used as image sources. */
export function safeImage(url: string | null | undefined): string | null {
  if (!url) return null
  const u = url.trim()
  if (u.startsWith("/") && !u.startsWith("//")) return u
  if (/^https:\/\//i.test(u)) return u
  return null
}
