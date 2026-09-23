var C = Object.defineProperty;
var D = (l, c, t) => c in l ? C(l, c, { enumerable: !0, configurable: !0, writable: !0, value: t }) : l[c] = t;
var g = (l, c, t) => D(l, typeof c != "symbol" ? c + "" : c, t);
const v = {
  en: { ci: "Check-in", co: "Check-out", guests: "Guests", adults: "Adults", children: "Children", age: "Age of child {n}", pick: "Age", under1: "Under 1", search: "Search", book: "Book now", close: "Close", booking: "Booking", done: "Done", less: "Fewer {what}", more: "More {what}", errDates: "Choose check-in and check-out dates.", errOrder: "Check-out must be after check-in.", errAges: "Add the age of each child.", a: "{n} adult", as: "{n} adults", c: "{n} child", cs: "{n} children" },
  tr: { ci: "Giriş", co: "Çıkış", guests: "Misafirler", adults: "Yetişkin", children: "Çocuk", age: "{n}. çocuğun yaşı", pick: "Yaş", under1: "1 yaşından küçük", search: "Ara", book: "Rezervasyon yap", close: "Kapat", booking: "Rezervasyon", done: "Tamam", less: "{what} azalt", more: "{what} artır", errDates: "Giriş ve çıkış tarihlerini seçin.", errOrder: "Çıkış, girişten sonra olmalıdır.", errAges: "Her çocuğun yaşını ekleyin.", a: "{n} yetişkin", as: "{n} yetişkin", c: "{n} çocuk", cs: "{n} çocuk" },
  de: { ci: "Anreise", co: "Abreise", guests: "Gäste", adults: "Erwachsene", children: "Kinder", age: "Alter von Kind {n}", pick: "Alter", under1: "Unter 1", search: "Suchen", book: "Jetzt buchen", close: "Schließen", booking: "Buchung", done: "Fertig", less: "Weniger {what}", more: "Mehr {what}", errDates: "Wählen Sie An- und Abreise.", errOrder: "Die Abreise muss nach der Anreise liegen.", errAges: "Geben Sie das Alter jedes Kindes an.", a: "{n} Erwachsener", as: "{n} Erwachsene", c: "{n} Kind", cs: "{n} Kinder" },
  ru: { ci: "Заезд", co: "Выезд", guests: "Гости", adults: "Взрослые", children: "Дети", age: "Возраст ребёнка {n}", pick: "Возраст", under1: "До 1 года", search: "Найти", book: "Забронировать", close: "Закрыть", booking: "Бронирование", done: "Готово", less: "Меньше: {what}", more: "Больше: {what}", errDates: "Выберите даты заезда и выезда.", errOrder: "Выезд должен быть позже заезда.", errAges: "Укажите возраст каждого ребёнка.", a: "Взрослых: {n}", as: "Взрослых: {n}", c: "Детей: {n}", cs: "Детей: {n}" },
  ro: { ci: "Sosire", co: "Plecare", guests: "Oaspeți", adults: "Adulți", children: "Copii", age: "Vârsta copilului {n}", pick: "Vârsta", under1: "Sub 1 an", search: "Caută", book: "Rezervă acum", close: "Închide", booking: "Rezervare", done: "Gata", less: "Mai puțini {what}", more: "Mai mulți {what}", errDates: "Alegeți datele de sosire și plecare.", errOrder: "Plecarea trebuie să fie după sosire.", errAges: "Adăugați vârsta fiecărui copil.", a: "{n} adult", as: "{n} adulți", c: "{n} copil", cs: "{n} copii" },
  pl: { ci: "Przyjazd", co: "Wyjazd", guests: "Goście", adults: "Dorośli", children: "Dzieci", age: "Wiek dziecka {n}", pick: "Wiek", under1: "Poniżej 1", search: "Szukaj", book: "Rezerwuj", close: "Zamknij", booking: "Rezerwacja", done: "Gotowe", less: "Mniej: {what}", more: "Więcej: {what}", errDates: "Wybierz daty przyjazdu i wyjazdu.", errOrder: "Wyjazd musi być po przyjeździe.", errAges: "Podaj wiek każdego dziecka.", a: "Dorośli: {n}", as: "Dorośli: {n}", c: "Dzieci: {n}", cs: "Dzieci: {n}" }
}, M = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i, x = { none: "0px", sm: "4px", md: "8px", lg: "12px", xl: "18px" }, $ = {
  Inter: '"Inter",',
  "DM Sans": '"DM Sans",',
  "Nunito Sans": '"Nunito Sans",',
  "Source Sans 3": '"Source Sans 3",',
  Lora: '"Lora",Georgia,',
  "Playfair Display": '"Playfair Display",Georgia,',
  System: ""
}, S = `
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
`, E = (l) => `${l.getFullYear()}-${String(l.getMonth() + 1).padStart(2, "0")}-${String(l.getDate()).padStart(2, "0")}`, w = (l, c) => {
  const [t, s, i] = l.split("-").map(Number);
  return E(new Date(t, s - 1, i + c, 12));
}, d = (l) => l.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
function A(l) {
  const c = l.length === 4 ? l.slice(1).split("").map((o) => o + o).join("") : l.slice(1), [t, s, i] = [0, 2, 4].map((o) => parseInt(c.slice(o, o + 2), 16) / 255).map((o) => o <= 0.03928 ? o / 12.92 : ((o + 0.055) / 1.055) ** 2.4), e = 0.2126 * t + 0.7152 * s + 0.0722 * i;
  return 1.05 / (e + 0.05) >= (e + 0.05) / 0.05 ? "#ffffff" : "#16181d";
}
const k = /* @__PURE__ */ new Map();
class z extends HTMLElement {
  constructor() {
    super();
    g(this, "root");
    g(this, "adults", 2);
    g(this, "ages", []);
    g(this, "siteName", "");
    g(this, "rendered", !1);
    g(this, "onMessage", (t) => {
      var i;
      const s = this.root.querySelector("iframe");
      s && t.source === s.contentWindow && ((i = t.data) == null ? void 0 : i.type) === "tex-booking:close" && this.close();
    });
    g(this, "closeGuests", () => {
    });
    g(this, "opener", null);
    g(this, "hostOverflow", "");
    this.root = this.attachShadow({ mode: "open" }), this.root.addEventListener("click", (t) => {
      const s = t.composedPath(), i = this.root.querySelector("#gp"), e = this.root.querySelector("#gb");
      i && e && !s.includes(i) && !s.includes(e) && this.closeGuests();
    });
  }
  get api() {
    return (this.getAttribute("api") || "").trim().replace(/\/+$/, "");
  }
  get site() {
    return (this.getAttribute("site") || "").trim().toLowerCase();
  }
  get uiLang() {
    return [this.getAttribute("lang"), document.documentElement.lang, navigator.language].map((s) => (s || "").slice(0, 2).toLowerCase()).find((s) => s in v) || "en";
  }
  t(t, s = {}) {
    return (v[this.uiLang][t] ?? v.en[t]).replace(/\{(\w+)\}/g, (i, e) => String(s[e] ?? ""));
  }
  connectedCallback() {
    window.addEventListener("message", this.onMessage), this.render(), this.loadTheme();
  }
  disconnectedCallback() {
    window.removeEventListener("message", this.onMessage);
  }
  attributeChangedCallback(t, s, i) {
    !this.rendered || s === i || (this.render(), (t === "site" || t === "api") && this.loadTheme());
  }
  async loadTheme() {
    if (!this.site) return;
    const t = `${this.api}|${this.site}`;
    k.has(t) || k.set(
      t,
      fetch(`${this.api}/api/method/kamra.tex.api.public.site?slug=${encodeURIComponent(this.site)}`, { credentials: "omit" }).then((u) => u.ok ? u.json() : null).then((u) => (u == null ? void 0 : u.message) ?? null).catch(() => null)
    );
    const s = await k.get(t), i = this.root.querySelector(".w");
    if (!s || !i) return;
    this.siteName = s.name || "";
    const e = s.branding || {};
    e.primary && M.test(e.primary) && (i.style.setProperty("--p", e.primary), i.style.setProperty("--op", A(e.primary)), i.style.setProperty("--pi", A(e.primary) === "#ffffff" ? e.primary : "#16181d")), e.font && e.font in $ && i.style.setProperty("--f", `${$[e.font]}ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif`), e.radius && e.radius in x && i.style.setProperty("--r", x[e.radius]), i.style.setProperty("--br", e.button_style === "pill" ? "999px" : x[e.radius ?? "md"] ?? "8px"), e.button_style === "outline" && (i.dataset.btn = "outline");
    const o = this.root.querySelector(".mt");
    o && (o.textContent = this.siteName || this.t("booking"));
    const n = s.texts ?? {}, r = [this.uiLang, s.default_language].map((u) => {
      var b;
      return u ? (b = n[u]) == null ? void 0 : b.search_button : null;
    }).find((u) => typeof u == "string" && u.trim()), f = this.root.querySelector(".go");
    f && typeof r == "string" && (f.textContent = r.trim());
  }
  url(t, s) {
    const i = new URLSearchParams(t);
    i.set("lang", this.uiLang);
    const e = this.getAttribute("hotel"), o = this.getAttribute("currency");
    e && i.set("hotel", e), o && /^[A-Z]{3}$/.test(o) && i.set("currency", o);
    const n = (this.getAttribute("market") || "").trim(), r = (this.getAttribute("country") || "").trim();
    return /^[A-Za-z0-9_-]{1,40}$/.test(n) && i.set("market", n), /^[A-Za-z]{2}$/.test(r) && i.set("country", r.toUpperCase()), s && i.set("embed", "1"), `${this.api}/book/${encodeURIComponent(this.site)}?${i}`;
  }
  guestsText() {
    const t = this.ages.length;
    return [this.t(this.adults === 1 ? "a" : "as", { n: this.adults }), t ? this.t(t === 1 ? "c" : "cs", { n: t }) : ""].filter(Boolean).join(", ");
  }
  render() {
    this.rendered = !0;
    const t = this.getAttribute("mode") || "search", s = E(/* @__PURE__ */ new Date());
    if (t === "button") {
      this.root.innerHTML = `<style>${S}</style><div class="w" part="root"><button type="button" class="bk" part="button">${d(this.getAttribute("label") || this.t("book"))}</button>${this.modalHtml()}</div>`, this.root.querySelector(".bk").addEventListener("click", () => this.open(this.url({}, !0))), this.wireModal();
      return;
    }
    this.root.innerHTML = `<style>${S}</style>
<div class="w" part="root">
  <form novalidate part="form">
    <div class="f"><label for="ci">${d(this.t("ci"))}</label><input id="ci" type="date" min="${s}" required></div>
    <div class="f"><label for="co">${d(this.t("co"))}</label><input id="co" type="date" min="${w(s, 1)}" required></div>
    <div class="f g"><span class="lb" id="gl">${d(this.t("guests"))}</span>
      <button type="button" class="gb" id="gb" aria-expanded="false" aria-controls="gp" aria-labelledby="gl gb"></button>
      <div class="pop" id="gp" role="group" aria-labelledby="gl" hidden></div>
    </div>
    <button type="submit" class="go" part="button">${d(this.t("search"))}</button>
    <p class="err" role="alert" id="er"></p>
  </form>
  ${this.modalHtml()}
</div>`;
    const i = (a) => this.root.querySelector(a), e = i("#ci"), o = i("#co");
    e.addEventListener("change", () => {
      e.value && (o.min = w(e.value, 1), (!o.value || o.value <= e.value) && (o.value = w(e.value, 1)));
    });
    const n = i("#gb"), r = i("#gp");
    n.textContent = this.guestsText();
    const f = typeof r.showPopover == "function", u = () => f ? r.matches(":popover-open") : !r.hidden, b = () => {
      const a = n.getBoundingClientRect(), p = Math.min(320, window.innerWidth - 16);
      r.style.width = `${p}px`, r.style.left = `${Math.max(8, Math.min(a.left, window.innerWidth - p - 8))}px`;
      const h = r.offsetHeight || 280, y = a.bottom + 6;
      r.style.top = `${y + h > window.innerHeight - 8 && a.top - 6 - h > 8 ? a.top - 6 - h : y}px`;
    }, m = (a, p = !0) => {
      var h;
      if (a !== u()) {
        if (f) return a ? r.showPopover() : r.hidePopover();
        r.hidden = !a, n.setAttribute("aria-expanded", String(a)), a ? (this.renderGuests(), (h = r.querySelector("button")) == null || h.focus()) : p && n.focus();
      }
    };
    f ? (r.setAttribute("popover", "auto"), r.hidden = !1, n.popoverTargetElement = r, r.addEventListener("beforetoggle", (a) => {
      a.newState === "open" && this.renderGuests();
    }), r.addEventListener("toggle", (a) => {
      var h;
      const p = a.newState === "open";
      n.setAttribute("aria-expanded", String(p)), p ? (b(), window.addEventListener("scroll", b, { passive: !0 }), window.addEventListener("resize", b), (h = r.querySelector("button:not(:disabled)")) == null || h.focus()) : (window.removeEventListener("scroll", b), window.removeEventListener("resize", b));
    })) : (n.addEventListener("click", () => m(r.hidden)), r.addEventListener("keydown", (a) => {
      a.key === "Escape" && (a.stopPropagation(), m(!1));
    }), this.closeGuests = () => m(!1, !1)), r.addEventListener("tex-done", () => {
      m(!1), n.focus();
    }), i("form").addEventListener("submit", (a) => {
      a.preventDefault();
      const p = i("#er");
      if (p.textContent = "", !e.value || !o.value)
        return p.textContent = this.t("errDates"), (e.value ? o : e).focus();
      if (o.value <= e.value || e.value < s)
        return p.textContent = this.t("errOrder"), o.focus();
      if (this.ages.some((L) => L === null))
        return p.textContent = this.t("errAges"), m(!0);
      const h = this.ages.length ? `${this.adults}-${this.ages.join("_")}` : `${this.adults}`;
      this.dispatchEvent(
        new CustomEvent("tex-booking:search", { bubbles: !0, composed: !0, detail: { checkIn: e.value, checkOut: o.value, adults: this.adults, children: this.ages.slice() } })
      );
      const y = { checkin: e.value, checkout: o.value, rooms: h };
      t === "redirect" ? window.location.assign(this.url(y, !1)) : this.open(this.url(y, !0));
    }), this.wireModal();
  }
  renderGuests() {
    const t = this.root.querySelector("#gp"), s = (e, o, n, r, f) => `
      <div class="row" role="group" aria-labelledby="${e}-l"><span id="${e}-l">${d(o)}</span>
        <span class="st"><button type="button" data-k="${e}" data-d="-1" aria-label="${d(this.t("less", { what: o }))}" ${n <= r ? "disabled" : ""}>−</button>
        <output aria-live="polite">${n}</output>
        <button type="button" data-k="${e}" data-d="1" aria-label="${d(this.t("more", { what: o }))}" ${n >= f ? "disabled" : ""}>+</button></span></div>`, i = (e) => `<option value="">${d(this.t("pick"))}</option>` + Array.from({ length: 18 }, (o, n) => `<option value="${n}" ${e === n ? "selected" : ""}>${n === 0 ? d(this.t("under1")) : n}</option>`).join("");
    t.innerHTML = s("ad", this.t("adults"), this.adults, 1, 8) + s("ch", this.t("children"), this.ages.length, 0, 6) + (this.ages.length ? `<div class="ages">${this.ages.map((e, o) => `<div class="f"><label for="age${o}">${d(this.t("age", { n: o + 1 }))}</label><select id="age${o}" data-i="${o}">${i(e)}</select></div>`).join("")}</div>` : "") + `<button type="button" class="dn">${d(this.t("done"))}</button>`, t.querySelectorAll("button[data-k]").forEach(
      (e) => e.addEventListener("click", () => {
        var n;
        const o = Number(e.dataset.d);
        e.dataset.k === "ad" ? this.adults = Math.min(8, Math.max(1, this.adults + o)) : this.ages = o > 0 ? [...this.ages, null].slice(0, 6) : this.ages.slice(0, -1), this.renderGuests(), (n = this.root.querySelector(`button[data-k="${e.dataset.k}"][data-d="${o}"]`)) == null || n.focus(), this.root.querySelector("#gb").textContent = this.guestsText();
      })
    ), t.querySelectorAll("select").forEach(
      (e) => e.addEventListener("change", () => {
        this.ages[Number(e.dataset.i)] = e.value === "" ? null : Number(e.value);
      })
    ), t.querySelector(".dn").addEventListener("click", () => t.dispatchEvent(new Event("tex-done")));
  }
  modalHtml() {
    return `<dialog part="modal" aria-labelledby="mt"><div class="mb"><span class="mt" id="mt">${d(this.siteName || this.t("booking"))}</span><button type="button" class="x" aria-label="${d(this.t("close"))}">×</button></div><iframe title="${d(this.t("booking"))}" allow="payment"></iframe></dialog>`;
  }
  wireModal() {
    const t = this.root.querySelector("dialog");
    t.querySelector(".x").addEventListener("click", () => this.close()), t.addEventListener("cancel", (s) => {
      s.preventDefault(), this.close();
    });
  }
  open(t) {
    const s = this.root.querySelector("dialog"), i = s.querySelector("iframe");
    i.getAttribute("src") !== t && i.setAttribute("src", t), this.opener = this.root.activeElement ?? null, this.hostOverflow = document.documentElement.style.overflow, document.documentElement.style.overflow = "hidden", s.showModal(), i.focus();
  }
  close() {
    var s;
    const t = this.root.querySelector("dialog");
    t != null && t.open && (t.close(), document.documentElement.style.overflow = this.hostOverflow, (s = this.opener) == null || s.focus());
  }
}
g(z, "observedAttributes", ["site", "api", "lang", "mode", "hotel", "currency", "market", "country", "label"]);
customElements.get("tex-booking-widget") || customElements.define("tex-booking-widget", z);
export {
  z as TexBookingWidget
};
