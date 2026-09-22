// Public image upload for booking-site branding. The file is uploaded on its own
// (no doctype/docname, so no document is written through the generic upload);
// the returned /files/... URL is then saved with policies.save_record.
import { parseFrappeError, TexApiError } from "../../lib/api"

export const MAX_IMAGE_BYTES = 2 * 1024 * 1024
// SVG is excluded: served from /files it could carry script when opened directly
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"]

export async function uploadPublicImage(file: File): Promise<string> {
  const token = (window as unknown as { csrf_token?: string }).csrf_token
  const body = new FormData()
  body.append("file", file, file.name)
  body.append("is_private", "0")
  body.append("folder", "Home")
  const headers: Record<string, string> = { Accept: "application/json" }
  if (token && token !== "None") headers["X-Frappe-CSRF-Token"] = token
  let res: Response
  try {
    res = await fetch("/api/method/upload_file", { method: "POST", body, headers, credentials: "include" })
  } catch {
    throw new TexApiError("Can't reach the server. Check your connection and try again.", 0, "NetworkError")
  }
  if (!res.ok) throw parseFrappeError(await res.text(), res.status)
  const json = (await res.json()) as { message?: { file_url?: string } }
  const url = json.message?.file_url
  if (!url) throw new TexApiError("Upload failed.", res.status, "UploadError")
  return url
}
