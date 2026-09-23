// Image upload for booking-site branding, checked on the server (G-83): the TEX endpoint
// accepts only PNG, JPEG, GIF or WebP bytes of at most 2 MB, needs booking_site.edit for the
// site (or, for a site being created, its hotel or hotel group) and stores the image public,
// since guests see it. The checks below only save a round trip. The returned /files/... URL
// is then saved with policies.save_record.
import { parseFrappeError, TexApiError } from "../../lib/api"

export const MAX_IMAGE_BYTES = 2 * 1024 * 1024
// SVG is excluded: served from /files it could carry script when opened directly
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"]

/** What the image is for: a saved site, else the hotel or hotel group a new site will serve. */
export interface ImageTarget {
  site?: string | null
  property?: string | null
  hotel_group?: string | null
}

export async function uploadPublicImage(file: File, target: ImageTarget): Promise<string> {
  const token = (window as unknown as { csrf_token?: string }).csrf_token
  const body = new FormData()
  body.append("file", file, file.name)
  if (target.site) body.append("site", target.site)
  else if (target.property) body.append("property", target.property)
  else if (target.hotel_group) body.append("hotel_group", target.hotel_group)
  const headers: Record<string, string> = { Accept: "application/json" }
  if (token && token !== "None") headers["X-Frappe-CSRF-Token"] = token
  let res: Response
  try {
    res = await fetch("/api/method/kamra.tex.api.admin.upload_site_image", { method: "POST", body, headers, credentials: "include" })
  } catch {
    throw new TexApiError("Can't reach the server. Check your connection and try again.", 0, "NetworkError")
  }
  if (!res.ok) throw parseFrappeError(await res.text(), res.status)
  const json = (await res.json()) as { message?: { file_url?: string } }
  const url = json.message?.file_url
  if (!url) throw new TexApiError("Upload failed.", res.status, "UploadError")
  return url
}
