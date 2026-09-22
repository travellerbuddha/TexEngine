// <tex-booking-widget site="slug" api="https://hotel.example" lang="tr" mode="search">
//
// Embeddable search widget for hotel websites (R-30, ADR-012). Framework-free and
// rendered into a Shadow DOM, so host CSS cannot reach it and its CSS cannot leak
// out. Themed from the booking site's safe branding tokens. "Search" opens the
// booking engine (/book/<site>?…) in a modal iframe (mode="search" | "modal"),
// navigates to it (mode="redirect"), or mode="button" renders a single button.
//
// Attributes: site (required), api (TEX host; default: same origin), lang, mode,
// hotel, currency, label (button text for mode="button").
// Events: "tex-booking:search" (detail: { checkIn, checkOut, adults, children }).

type Lang = "en" | "tr" | "de" | "ru" | "ro" | "pl"

const T: Record<Lang, Record<string, string>> = {
  en: { ci: "Check-in", co: "Check-out", guests: "Guests", adults: "Adults", children: "Children", age: "Age of child {n}", pick: "Age", under1: "Under 1", search: "Search", book: "Book now", close: "Close", booking: "Booking", done: "Done", less: "Fewer {what}", more: "More {what}", errDates: "Choose check-in and check-out dates.", errOrder: "Check-out must be after check-in.", errAges: "Add the age of each child.", a: "{n} adult", as: "{n} adults", c: "{n} child", cs: "{n} children" },
  tr: { ci: "Giriş", co: "Çıkış", guests: "Misafirler", adults: "Yetişkin", children: "Çocuk", age: "{n}. çocuğun yaşı", pick: "Yaş", under1: "1 yaşından küçük", search: "Ara", book: "Rezervasyon yap", close: "Kapat", booking: "Rezervasyon", done: "Tamam", less: "{what} azalt", more: "{what} artır", errDates: "Giriş ve çıkış tarihlerini seçin.", errOrder: "Çıkış, girişten sonra olmalıdır.", errAges: "Her çocuğun yaşını ekleyin.", a: "{n} yetişkin", as: "{n} yetişkin", c: "{n} çocuk", cs: "{n} çocuk" },
  de: { ci: "Anreise", co: "Abreise", guests: "Gäste", adults: "Erwachsene", children: "Kinder", age: "Alter von Kind {n}", pick: "Alter", under1: "Unter 1", search: "Suchen", book: "Jetzt buchen", close: "Schließen", booking: "Buchung", done: "Fertig", less: "Weniger {what}", more: "Mehr {what}", errDates: "Wählen Sie An- und Abreise.", errOrder: "Die Abreise muss nach der Anreise liegen.", errAges: "Geben Sie das Alter jedes Kindes an.", a: "{n} Erwachsener", as: "{n} Erwachsene", c: "{n} Kind", cs: "{n} Kinder" },
  ru: { ci: "Заезд", co: "Выезд", guests: "Гости", adults: "Взрослые", children: "Дети", age: "Возраст ребёнка {n}", pick: "Возраст", under1: "До 1 года", search: "Найти", book: "Забронировать", close: "Закрыть", booking: "Бронирование", done: "Готово", less: "Меньше: {what}", more: "Больше: {what}", errDates: "Выберите даты заезда и выезда.", errOrder: "Выезд должен быть позже заезда.", errAges: "Укажите возраст каждого ребёнка.", a: "Взрослых: {n}", as: "Взрослых: {n}", c: "Детей: {n}", cs: "Детей: {n}" },
  ro: { ci: "Sosire", co: "Plecare", guests: "Oaspeți", adults: "Adulți", children: "Copii", age: "Vârsta copilului {n}", pick: "Vârsta", under1: "Sub 1 an", search: "Caută", book: "Rezervă acum", close: "Închide", booking: "Rezervare", done: "Gata", less: "Mai puțini {what}", more: "Mai mulți {what}", errDates: "Alegeți datele de sosire și plecare.", errOrder: "Plecarea trebuie să fie după sosire.", errAges: "Adăugați vârsta fiecărui copil.", a: "{n} adult", as: "{n} adulți", c: "{n} copil", cs: "{n} copii" },
  pl: { ci: "Przyjazd", co: "Wyjazd", guests: "Goście", adults: "Dorośli", children: "Dzieci", age: "Wiek dziecka {n}", pick: "Wiek", under1: "Poniżej 1", search: "Szukaj", book: "Rezerwuj", close: "Zamknij", booking: "Rezerwacja", done: "Gotowe", less: "Mniej: {what}", more: "Więcej: {what}", errDates: "Wybierz daty przyjazdu i wyjazdu.", errOrder: "Wyjazd musi być po przyjeździe.", errAges: "Podaj wiek każdego dziecka.", a: "Dorośli: {n}", as: "Dorośli: {n}", c: "Dzieci: {n}", cs: "Dzieci: {n}" },
}

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i
const RADIUS: Record<string, string> = { none: "0px", sm: "4px", md: "8px", lg: "12px", xl: "18px" }
const FONTS: Record<string, string> = {
  Inter: '"Inter",',
  "DM Sans": '"DM Sans",',
  "Nunito Sans": '"Nunito Sans",',
  "Source Sans 3": '"Source Sans 3",',
  Lora: '"Lora",Georgia,',
  "Playfair Display": '"Playfair Display",Georgia,',
  System: "",
}

const CSS = `
:host{all:initial;display:block;contain:layout style;color-scheme:light}
:host([hidden]){display:none}
*,*::before,*::after{box-sizing:border-box}
.w{all:initial;display:block;--p:#1c3fa8;--op:#fff;--ink:#16181d;--mut:#595d65;--line:#c9c7c1;--r:8px;--br:8px;font:400 15px/1.4 var(--f,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif);color:var(--ink);container-type:inline-size}
form{display:grid;gap:10px;grid-template-columns:1fr 1fr;align-items:end;background:#fff;border:1px solid #e3e2de;border-radius:calc(var(--r) + 4px);padding:12px;box-shadow:0 2px 10px rgb(22 24 29/.08);margin:0}
@container (min-width:620px){form{grid-template-columns:1fr 1fr 1.2fr auto}}
.f{display:flex;flex-direction:column;gap:4px;min-width:0;position:relative}
.g,.go{grid-column:1/-1}
@container (min-width:620px){.g,.go{grid-column:auto}}
label,.lb{font-size:13px;font-weight:600;color:#3b3f47}
input,select,.gb{font:inherit;font-size:16px;color:var(--ink);background:#fff;border:1.5px solid var(--line);border-radius:var(--r);min-height:46px;padding:8px 10px;width:100%;margin:0}
.gb{text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
input:focus-visible,select:focus-visible,button:focus-visible{outline:3px solid var(--pi,var(--p));outline-offset:2px}
.go,.bk{font:inherit;font-weight:700;font-size:16px;min-height:46px;padding:10px 22px;border-radius:var(--br);border:1.5px solid var(--p);background:var(--p);color:var(--op);cursor:pointer}
.w[data-btn=outline] .go,.w[data-btn=outline] .bk{background:#fff;color:var(--pi)}
.go:hover,.bk:hover{filter:brightness(.93)}
.err{grid-column:1/-1;margin:0;color:#b42318;font-size:14px;font-weight:600}
.err:empty{display:none}
.pop{background:#fff;color:var(--ink);font:inherit;border:1px solid #e3e2de;border-radius:calc(var(--r) + 4px);box-shadow:0 18px 48px -12px rgb(22 24 29/.3);padding:14px;margin-top:6px}
.pop[popover]{position:fixed;inset:auto;margin:0;width:320px;max-width:calc(100vw - 16px)}
.pop[hidden]{display:none}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:6px 0}
.st{display:flex;align-items:center;gap:10px}
.st button{width:40px;height:40px;border-radius:50%;border:1.5px solid var(--line);background:#fff;font:600 20px/1 system-ui;color:#3b3f47;cursor:pointer}
.st button:disabled{opacity:.35;cursor:default}
.st output{min-width:20px;text-align:center;font-weight:700}
.ages{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:6px}
.ages label{font-size:12px}
.dn{margin-top:10px;width:100%;min-height:42px;border-radius:var(--br);border:0;background:var(--p);color:var(--op);font:inherit;font-weight:700;cursor:pointer}
dialog{padding:0;border:0;width:100vw;height:100dvh;max-width:100vw;max-height:100dvh;margin:0;background:#fff;overflow:hidden}
dialog[open]{display:flex;flex-direction:column}
dialog::backdrop{background:rgb(15 17 21/.55)}
@media (min-width:720px){dialog{width:min(1180px,94vw);height:min(900px,92dvh);margin:auto;border-radius:16px;box-shadow:0 24px 64px -16px rgb(0 0 0/.45)}}
.mb{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:6px 8px 6px 16px;border-bottom:1px solid #e3e2de;font-weight:700;font-size:15px;min-height:52px}
.x{width:44px;height:44px;border-radius:50%;border:0;background:transparent;font:400 26px/1 system-ui;color:#3b3f47;cursor:pointer}
.x:hover{background:#f2f1ee}
iframe{flex:1;width:100%;border:0;display:block}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
`

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
const addDays = (s: string, n: number) => {
  const [y, m, d] = s.split("-").map(Number)
  return iso(new Date(y, m - 1, d + n, 12))
}
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

function contrastText(hex: string) {
  const h = hex.length === 4 ? hex.slice(1).split("").map((c) => c + c).join("") : hex.slice(1)
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  const L = 0.2126 * r + 0.7152 * g + 0.0722 * b
  return (1.05 / (L + 0.05)) >= ((L + 0.05) / 0.05) ? "#ffffff" : "#16181d"
}

interface SiteInfo {
  name?: string
  default_language?: string
  branding?: { primary?: string; font?: string; radius?: string; button_style?: string }
}

const themeCache = new Map<string, Promise<SiteInfo | null>>()

export class TexBookingWidget extends HTMLElement {
  static observedAttributes = ["site", "api", "lang", "mode", "hotel", "currency", "label"]
  private root: ShadowRoot
  private adults = 2
  private ages: (number | null)[] = []
  private siteName = ""
  private rendered = false
  private onMessage = (e: MessageEvent) => {
    const frame = this.root.querySelector("iframe")
    if (frame && e.source === frame.contentWindow && (e.data as { type?: string })?.type === "tex-booking:close") this.close()
  }

  private closeGuests: () => void = () => undefined

  constructor() {
    super()
    this.root = this.attachShadow({ mode: "open" })
    // a click anywhere else in the widget closes the guests panel
    this.root.addEventListener("click", (e) => {
      const path = e.composedPath()
      const gp = this.root.querySelector("#gp")
      const gb = this.root.querySelector("#gb")
      if (gp && gb && !path.includes(gp) && !path.includes(gb)) this.closeGuests()
    })
  }

  private get api() {
    return (this.getAttribute("api") || "").trim().replace(/\/+$/, "")
  }
  private get site() {
    return (this.getAttribute("site") || "").trim().toLowerCase()
  }
  private get uiLang(): Lang {
    const cand = [this.getAttribute("lang"), document.documentElement.lang, navigator.language].map((l) => (l || "").slice(0, 2).toLowerCase())
    return (cand.find((l) => l in T) as Lang) || "en"
  }
  private t(k: string, v: Record<string, string | number> = {}) {
    return (T[this.uiLang][k] ?? T.en[k]).replace(/\{(\w+)\}/g, (_, x: string) => String(v[x] ?? ""))
  }

  connectedCallback() {
    window.addEventListener("message", this.onMessage)
    this.render()
    void this.loadTheme()
  }
  disconnectedCallback() {
    window.removeEventListener("message", this.onMessage)
  }
  attributeChangedCallback(name: string, a: string | null, b: string | null) {
    if (!this.rendered || a === b) return
    this.render()
    if (name === "site" || name === "api") void this.loadTheme()
  }

  private async loadTheme() {
    if (!this.site) return
    const key = `${this.api}|${this.site}`
    if (!themeCache.has(key))
      themeCache.set(
        key,
        fetch(`${this.api}/api/method/kamra.tex.api.public.site?slug=${encodeURIComponent(this.site)}`, { credentials: "omit" })
          .then((r) => (r.ok ? r.json() : null))
          .then((j) => (j?.message as SiteInfo) ?? null)
          .catch(() => null),
      )
    const s = await themeCache.get(key)
    const w = this.root.querySelector<HTMLElement>(".w")
    if (!s || !w) return
    this.siteName = s.name || ""
    const b = s.branding || {}
    if (b.primary && HEX.test(b.primary)) {
      w.style.setProperty("--p", b.primary)
      w.style.setProperty("--op", contrastText(b.primary))
      w.style.setProperty("--pi", contrastText(b.primary) === "#ffffff" ? b.primary : "#16181d")
    }
    if (b.font && b.font in FONTS) w.style.setProperty("--f", `${FONTS[b.font]}ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif`)
    if (b.radius && b.radius in RADIUS) w.style.setProperty("--r", RADIUS[b.radius])
    w.style.setProperty("--br", b.button_style === "pill" ? "999px" : RADIUS[b.radius ?? "md"] ?? "8px")
    if (b.button_style === "outline") w.dataset.btn = "outline"
    const title = this.root.querySelector(".mt")
    if (title) title.textContent = this.siteName || this.t("booking")
  }

  private url(params: Record<string, string>, embed: boolean) {
    const q = new URLSearchParams(params)
    q.set("lang", this.uiLang)
    const hotel = this.getAttribute("hotel")
    const ccy = this.getAttribute("currency")
    if (hotel) q.set("hotel", hotel)
    if (ccy && /^[A-Z]{3}$/.test(ccy)) q.set("currency", ccy)
    if (embed) q.set("embed", "1")
    return `${this.api}/book/${encodeURIComponent(this.site)}?${q}`
  }

  private guestsText() {
    const kids = this.ages.length
    return [this.t(this.adults === 1 ? "a" : "as", { n: this.adults }), kids ? this.t(kids === 1 ? "c" : "cs", { n: kids }) : ""].filter(Boolean).join(", ")
  }

  private render() {
    this.rendered = true
    const mode = this.getAttribute("mode") || "search"
    const today = iso(new Date())
    if (mode === "button") {
      this.root.innerHTML = `<style>${CSS}</style><div class="w" part="root"><button type="button" class="bk" part="button">${esc(this.getAttribute("label") || this.t("book"))}</button>${this.modalHtml()}</div>`
      this.root.querySelector(".bk")!.addEventListener("click", () => this.open(this.url({}, true)))
      this.wireModal()
      return
    }
    this.root.innerHTML = `<style>${CSS}</style>
<div class="w" part="root">
  <form novalidate part="form">
    <div class="f"><label for="ci">${esc(this.t("ci"))}</label><input id="ci" type="date" min="${today}" required></div>
    <div class="f"><label for="co">${esc(this.t("co"))}</label><input id="co" type="date" min="${addDays(today, 1)}" required></div>
    <div class="f g"><span class="lb" id="gl">${esc(this.t("guests"))}</span>
      <button type="button" class="gb" id="gb" aria-expanded="false" aria-controls="gp" aria-labelledby="gl gb"></button>
      <div class="pop" id="gp" role="group" aria-labelledby="gl" hidden></div>
    </div>
    <button type="submit" class="go" part="button">${esc(this.t("search"))}</button>
    <p class="err" role="alert" id="er"></p>
  </form>
  ${this.modalHtml()}
</div>`
    const $ = <E extends Element>(s: string) => this.root.querySelector(s) as E
    const ci = $<HTMLInputElement>("#ci")
    const co = $<HTMLInputElement>("#co")
    ci.addEventListener("change", () => {
      if (!ci.value) return
      co.min = addDays(ci.value, 1)
      if (!co.value || co.value <= ci.value) co.value = addDays(ci.value, 1)
    })
    const gb = $<HTMLButtonElement>("#gb")
    const gp = $<HTMLDivElement>("#gp")
    gb.textContent = this.guestsText()
    // Top layer (Popover API) so host containers with overflow:hidden or transforms
    // cannot clip the panel; without it the panel simply expands in place.
    type PopEl = HTMLElement & { showPopover(): void; hidePopover(): void }
    type ToggleEv = Event & { newState?: string }
    const topLayer = typeof (gp as Partial<PopEl>).showPopover === "function"
    const isOpen = () => (topLayer ? gp.matches(":popover-open") : !gp.hidden)
    const place = () => {
      const r = gb.getBoundingClientRect()
      const w = Math.min(320, window.innerWidth - 16)
      gp.style.width = `${w}px`
      gp.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`
      const h = gp.offsetHeight || 280
      const below = r.bottom + 6
      gp.style.top = `${below + h > window.innerHeight - 8 && r.top - 6 - h > 8 ? r.top - 6 - h : below}px`
    }
    const setOpen = (open: boolean, focusBack = true) => {
      if (open === isOpen()) return
      if (topLayer) return open ? (gp as PopEl).showPopover() : (gp as PopEl).hidePopover()
      gp.hidden = !open
      gb.setAttribute("aria-expanded", String(open))
      if (open) {
        this.renderGuests()
        gp.querySelector<HTMLButtonElement>("button")?.focus()
      } else if (focusBack) gb.focus()
    }
    if (topLayer) {
      gp.setAttribute("popover", "auto")
      gp.hidden = false
      ;(gb as HTMLButtonElement & { popoverTargetElement: Element | null }).popoverTargetElement = gp
      gp.addEventListener("beforetoggle", (e) => {
        if ((e as ToggleEv).newState === "open") this.renderGuests()
      })
      gp.addEventListener("toggle", (e) => {
        const open = (e as ToggleEv).newState === "open"
        gb.setAttribute("aria-expanded", String(open))
        if (open) {
          place()
          window.addEventListener("scroll", place, { passive: true })
          window.addEventListener("resize", place)
          gp.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus()
        } else {
          window.removeEventListener("scroll", place)
          window.removeEventListener("resize", place)
        }
      })
    } else {
      gb.addEventListener("click", () => setOpen(gp.hidden))
      gp.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          e.stopPropagation()
          setOpen(false)
        }
      })
      this.closeGuests = () => setOpen(false, false)
    }
    gp.addEventListener("tex-done", () => {
      setOpen(false)
      gb.focus()
    })
    $<HTMLFormElement>("form").addEventListener("submit", (e) => {
      e.preventDefault()
      const er = $<HTMLParagraphElement>("#er")
      er.textContent = ""
      if (!ci.value || !co.value) {
        er.textContent = this.t("errDates")
        return (ci.value ? co : ci).focus()
      }
      if (co.value <= ci.value || ci.value < today) {
        er.textContent = this.t("errOrder")
        return co.focus()
      }
      if (this.ages.some((a) => a === null)) {
        er.textContent = this.t("errAges")
        return setOpen(true)
      }
      const rooms = this.ages.length ? `${this.adults}-${this.ages.join(".")}` : `${this.adults}`
      this.dispatchEvent(
        new CustomEvent("tex-booking:search", { bubbles: true, composed: true, detail: { checkIn: ci.value, checkOut: co.value, adults: this.adults, children: this.ages.slice() } }),
      )
      const params = { checkin: ci.value, checkout: co.value, rooms }
      if (mode === "redirect") window.location.assign(this.url(params, false))
      else this.open(this.url(params, true))
    })
    this.wireModal()
  }

  private renderGuests() {
    const gp = this.root.querySelector<HTMLDivElement>("#gp")!
    const stepper = (id: string, label: string, value: number, min: number, max: number) => `
      <div class="row" role="group" aria-labelledby="${id}-l"><span id="${id}-l">${esc(label)}</span>
        <span class="st"><button type="button" data-k="${id}" data-d="-1" aria-label="${esc(this.t("less", { what: label }))}" ${value <= min ? "disabled" : ""}>−</button>
        <output aria-live="polite">${value}</output>
        <button type="button" data-k="${id}" data-d="1" aria-label="${esc(this.t("more", { what: label }))}" ${value >= max ? "disabled" : ""}>+</button></span></div>`
    const opts = (sel: number | null) =>
      `<option value="">${esc(this.t("pick"))}</option>` +
      Array.from({ length: 18 }, (_, a) => `<option value="${a}" ${sel === a ? "selected" : ""}>${a === 0 ? esc(this.t("under1")) : a}</option>`).join("")
    gp.innerHTML =
      stepper("ad", this.t("adults"), this.adults, 1, 8) +
      stepper("ch", this.t("children"), this.ages.length, 0, 6) +
      (this.ages.length
        ? `<div class="ages">${this.ages.map((a, i) => `<div class="f"><label for="age${i}">${esc(this.t("age", { n: i + 1 }))}</label><select id="age${i}" data-i="${i}">${opts(a)}</select></div>`).join("")}</div>`
        : "") +
      `<button type="button" class="dn">${esc(this.t("done"))}</button>`
    gp.querySelectorAll<HTMLButtonElement>("button[data-k]").forEach((b) =>
      b.addEventListener("click", () => {
        const d = Number(b.dataset.d)
        if (b.dataset.k === "ad") this.adults = Math.min(8, Math.max(1, this.adults + d))
        else this.ages = d > 0 ? [...this.ages, null].slice(0, 6) : this.ages.slice(0, -1)
        this.renderGuests()
        this.root.querySelector<HTMLButtonElement>(`button[data-k="${b.dataset.k}"][data-d="${d}"]`)?.focus()
        this.root.querySelector("#gb")!.textContent = this.guestsText()
      }),
    )
    gp.querySelectorAll<HTMLSelectElement>("select").forEach((s) =>
      s.addEventListener("change", () => {
        this.ages[Number(s.dataset.i)] = s.value === "" ? null : Number(s.value)
      }),
    )
    gp.querySelector(".dn")!.addEventListener("click", () => gp.dispatchEvent(new Event("tex-done")))
  }

  private modalHtml() {
    return `<dialog part="modal" aria-labelledby="mt"><div class="mb"><span class="mt" id="mt">${esc(this.siteName || this.t("booking"))}</span><button type="button" class="x" aria-label="${esc(this.t("close"))}">×</button></div><iframe title="${esc(this.t("booking"))}" allow="payment"></iframe></dialog>`
  }

  private wireModal() {
    const dlg = this.root.querySelector("dialog")!
    dlg.querySelector(".x")!.addEventListener("click", () => this.close())
    dlg.addEventListener("cancel", (e) => {
      e.preventDefault()
      this.close()
    })
  }

  private opener: HTMLElement | null = null

  private open(src: string) {
    const dlg = this.root.querySelector("dialog")!
    const frame = dlg.querySelector("iframe")!
    if (frame.getAttribute("src") !== src) frame.setAttribute("src", src)
    this.opener = (this.root.activeElement as HTMLElement) ?? null
    // stop the host page scrolling behind the modal; restored exactly on close
    this.hostOverflow = document.documentElement.style.overflow
    document.documentElement.style.overflow = "hidden"
    dlg.showModal()
    frame.focus()
  }

  private hostOverflow = ""

  close() {
    const dlg = this.root.querySelector("dialog")
    if (!dlg?.open) return
    dlg.close()
    document.documentElement.style.overflow = this.hostOverflow
    this.opener?.focus()
  }
}

if (!customElements.get("tex-booking-widget")) customElements.define("tex-booking-widget", TexBookingWidget)
