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

/** The saved tables with the client row keys of the tables that were `sent`: for every table
 * whose saved and sent copies have the same length, row i of the saved copy takes `_key` of row
 * i of the sent copy (the server stores rows in the posted order), so selection, focus, open
 * panels and issue anchors survive a save. Tables of another length (the server added or dropped
 * rows) keep the saved keys. Pure: returns new arrays and rows, never changes its inputs. */
export function keepKeys<T extends Record<string, readonly { _key: string }[]>>(saved: T, sent: Partial<T>): T {
  const next = { ...saved }
  for (const k of Object.keys(saved) as (keyof T)[]) {
    const s = saved[k]
    const o = sent[k]
    if (!o || o.length !== s.length) continue
    next[k] = s.map((row, i) => ({ ...row, _key: o[i]._key })) as unknown as T[keyof T]
  }
  return next
}
