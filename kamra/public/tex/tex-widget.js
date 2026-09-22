class e extends HTMLElement {
  connectedCallback() {
    const t = this.shadowRoot ?? this.attachShadow({ mode: "open" });
    t.textContent = "TEX booking widget";
  }
}
customElements.get("tex-booking-widget") || customElements.define("tex-booking-widget", e);
export {
  e as TexBookingWidget
};
