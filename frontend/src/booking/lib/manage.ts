// Which actions the manage page offers on a room (O-16, audit Part 2A). The server decides both
// dates: a change while `can_change` (confirmed, arriving today or later), a cancellation while
// `can_cancel` (before the arrival day — from that day the stay may have started). The cancellation
// is stricter on purpose (ADR-064); a room the server says nothing about offers no cancellation.

/** Reservation statuses extras can still be added to (services/addons.py OPEN_STATUSES). */
const EXTRAS_OPEN = new Set(["Confirmed", "Pending Payment", "Held"])
/** A stay the guest no longer manages online. */
const CLOSED = new Set(["Cancelled", "Checked Out", "No Show", "Checked In"])

export type RoomActions = { change: boolean; extras: boolean; cancel: boolean }

export function roomActions(
  room: { status: string; can_change?: boolean; can_cancel?: boolean },
  booking: { self_service?: boolean; changes_blocked?: string | null },
): RoomActions {
  if (!booking.self_service || CLOSED.has(room.status)) return { change: false, extras: false, cancel: false }
  return {
    change: !booking.changes_blocked && room.can_change !== false,
    extras: EXTRAS_OPEN.has(room.status),
    cancel: room.can_cancel === true,
  }
}
