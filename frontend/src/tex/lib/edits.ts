// Editors keep working while a save is in flight: what the user changes meanwhile must survive
// the save's answer, or it is silently dropped (and the next save sends it away too).

/** The saved copy once a save has answered, except where the user changed something while it
 * was in flight: a key whose value in `cur` differs from what was `sent` keeps the user's value.
 * Every other key takes the saved value (the server may have normalised or filled it in). Values
 * compare as JSON; `keys` defaults to the saved copy's keys. */
export function overSaved<T extends object>(saved: T, sent: T, cur: T, keys: readonly (keyof T)[] = Object.keys(saved) as (keyof T)[]): T {
  const next = { ...saved }
  for (const k of keys) if (JSON.stringify(cur[k]) !== JSON.stringify(sent[k])) next[k] = cur[k]
  return next
}
