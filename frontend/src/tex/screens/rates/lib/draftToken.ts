// The draft token (O-10, ADR-069): the editor saves with the draft's `modified` as it read it
// (`expected_modified`); the server refuses a save from an older read with `DraftChanged`.

/** A save refused because someone changed the draft after the editor read it. */
export function isDraftChanged(e: unknown): boolean {
  return typeof e === "object" && e !== null && (e as { type?: unknown }).type === "DraftChanged"
}
