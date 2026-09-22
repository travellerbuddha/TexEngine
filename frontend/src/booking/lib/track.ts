// Funnel events (R-38). The server records search / quote / guest details /
// payment started / booked itself; the browser only reports what the server cannot
// see: a room being looked at, and the guest leaving after a quote.
import { beacon } from "./api"
import { sessionId } from "./storage"

const viewed = new Set<string>()

export function trackRoomView(site: string, payload: Record<string, string | number | null>) {
  const key = JSON.stringify(payload)
  if (viewed.has(key)) return
  viewed.add(key)
  beacon("track", { site, session_id: sessionId(), event: "room_view", payload: JSON.stringify(payload) })
}

let armed: { site: string; payload: Record<string, unknown> } | null = null
let listening = false

function onPageHide() {
  if (!armed) return
  const { site, payload } = armed
  armed = null
  beacon("track", { site, session_id: sessionId(), event: "abandoned", payload: JSON.stringify(payload) })
}

/** After a quote: report "abandoned" if the page is left before booking. */
export function armAbandon(site: string, payload: Record<string, unknown>) {
  armed = { site, payload }
  if (!listening) {
    window.addEventListener("pagehide", onPageHide)
    listening = true
  }
}

/** Booking made, or the guest is leaving for the payment page on purpose. */
export function disarmAbandon() {
  armed = null
}
