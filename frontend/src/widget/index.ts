// <tex-booking-widget site="slug" api="https://hotel.example"> — embeddable search
// widget rendered into a Shadow DOM (ADR-012). Built separately by vite.widget.config.ts
// into kamra/public/tex/tex-widget.js.
export class TexBookingWidget extends HTMLElement {
  connectedCallback() {
    const root = this.shadowRoot ?? this.attachShadow({ mode: "open" })
    root.textContent = "TEX booking widget"
  }
}

if (!customElements.get("tex-booking-widget")) customElements.define("tex-booking-widget", TexBookingWidget)
