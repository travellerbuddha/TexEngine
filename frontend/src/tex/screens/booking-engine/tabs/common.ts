import type { Errors, Site } from "../site"

export interface TabProps {
  site: Site
  set: (patch: Partial<Site>) => void
  /** Translated error for a field, or undefined (respects "show after first save"). */
  err: (field: string) => string | undefined
  errors: Errors
  isNew: boolean
  dirty: boolean
  reload: () => void
}
