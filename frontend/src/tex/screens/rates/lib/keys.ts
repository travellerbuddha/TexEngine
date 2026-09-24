// Client row keys for the version editor's child-table rows (`Row._key`). No imports, so the pure
// Pricing Workspace modules (and their `node --test` tests) can create rows too. save_version drops
// every `_*` field; the read-only draft overlay maps `_key` to the rule ids it reports (§3.14).

let keySeq = 0

/** A new client-only row key, unique within this page load. */
export function newKey(): string {
  keySeq += 1
  return `r${Date.now().toString(36)}${keySeq}`
}
