// White-label theme tokens of the booking engine (booking/lib/branding.ts themeFrom, R-32): only
// validated hex colours (text kept readable), fonts from the allow-list, radius steps and a button
// style reach the page. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { contrast, DEFAULT_BRAND, FONTS, parseHex, themeFrom } from "../../src/booking/lib/branding.ts"

const rgb = (hex: string) => {
  const c = parseHex(hex)
  assert.ok(c, hex)
  return c
}
const WHITE = rgb("#ffffff")
const INK = rgb("#16181d")

test("colours: a valid hex is used, anything else falls back to the default", () => {
  assert.equal(themeFrom({ primary: "#0B3B5B" }).vars["--bk-primary"], "#0b3b5b")
  assert.equal(themeFrom({ primary: "#abc" }).vars["--bk-primary"], "#aabbcc")
  for (const bad of ["red", "#12345g", "url(x)", "#1234567", "", null, undefined])
    assert.equal(themeFrom({ primary: bad }).vars["--bk-primary"], DEFAULT_BRAND.primary.toLowerCase(), String(bad))
  assert.equal(themeFrom(null).vars["--bk-accent"], DEFAULT_BRAND.accent.toLowerCase())
})

test("contrast: text on the brand colours stays readable", () => {
  assert.equal(themeFrom({ primary: "#0B3B5B" }).vars["--bk-on-primary"], "#ffffff")
  assert.equal(themeFrom({ primary: "#F5E663" }).vars["--bk-on-primary"], "#16181d")
  for (const primary of ["#F5E663", "#FFFFFF", "#88CCEE", "#0B3B5B"]) {
    const v = themeFrom({ primary, accent: primary }).vars
    assert.ok(contrast(rgb(v["--bk-primary-ink"]), WHITE) >= 4.5, `primary ink ${primary}`)
    assert.ok(contrast(rgb(v["--bk-accent-ink"]), WHITE) >= 4.5, `accent ink ${primary}`)
  }
  // a dark page background is lightened until body text reads (7:1)
  for (const background of ["#000000", "#333333", "#F7F7F5"])
    assert.ok(contrast(rgb(themeFrom({ background }).vars["--bk-canvas"]), INK) >= 7, background)
})

test("fonts come from the allow-list only", () => {
  assert.equal(themeFrom({ font: "Lora" }).vars["--bk-font"], FONTS.Lora.stack)
  assert.equal(themeFrom({ font: "Lora" }).vars["--bk-heading-weight"], "600")
  for (const bad of ["Comic Sans", "Inter; background:url(x)", null])
    assert.equal(themeFrom({ font: bad }).vars["--bk-font"], FONTS.Inter.stack, String(bad))
})

test("radius steps and the button style", () => {
  assert.equal(themeFrom({ radius: "xl" }).vars["--bk-radius"], "18px")
  assert.equal(themeFrom({ radius: "huge" }).vars["--bk-radius"], "8px")
  assert.equal(themeFrom({ card_radius: "none" }).vars["--bk-card-radius"], "0px")
  assert.equal(themeFrom({}).vars["--bk-card-radius"], "16px")
  const pill = themeFrom({ button_style: "pill", radius: "sm" })
  assert.equal(pill.buttonStyle, "pill")
  assert.equal(pill.vars["--bk-button-radius"], "999px")
  const other = themeFrom({ button_style: "fancy", radius: "sm" })
  assert.equal(other.buttonStyle, "solid")
  assert.equal(other.vars["--bk-button-radius"], "4px")
})
