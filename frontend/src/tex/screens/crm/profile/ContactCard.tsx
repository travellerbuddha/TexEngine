import type { ReactNode } from "react"
import { Tag } from "lucide-react"
import { date } from "../../../lib/format"
import { TEX_LANGS, useTexT } from "../../../i18n"
import { Badge, Card, CardBody, CardHeader, DescriptionList } from "../../../ui"
import { splitTags } from "../lib"
import type { Guest } from "../types"

export function languageLabel(code: string | null | undefined) {
  if (!code) return null
  return TEX_LANGS.find((l) => l.code === code)?.label ?? code
}

export const GENDER_KEYS: Record<string, string> = {
  Male: "crm.gender.male",
  Female: "crm.gender.female",
  Other: "crm.gender.other",
  "Prefer not to say": "crm.gender.undisclosed",
}

export function ContactCard({ guest, actions }: { guest: Guest; actions?: ReactNode }) {
  const { t } = useTexT()
  const tags = splitTags(guest.tex_tags)
  const address = [guest.address_line, guest.city].filter(Boolean).join(", ")
  return (
    <Card>
      <CardHeader title={t("crm.profile.contact")} actions={actions} />
      <CardBody className="space-y-5">
        <DescriptionList
          items={[
            { label: t("crm.field.email"), value: guest.email ? <a className="text-tex-700 hover:underline" href={`mailto:${guest.email}`}>{guest.email}</a> : "—" },
            { label: t("crm.field.phone"), value: guest.phone ? <a className="text-tex-700 hover:underline" href={`tel:${guest.phone}`}>{guest.phone}</a> : "—" },
            { label: t("crm.field.language"), value: languageLabel(guest.tex_language) ?? "—" },
            { label: t("crm.field.country"), value: guest.tex_country || "—" },
            { label: t("crm.field.market"), value: guest.tex_market || "—" },
            { label: t("crm.field.nationality"), value: guest.nationality || "—" },
            { label: t("crm.field.dob"), value: date(guest.date_of_birth) },
            { label: t("crm.field.gender"), value: guest.gender ? t(GENDER_KEYS[guest.gender] ?? guest.gender) : "—" },
            { label: t("crm.field.address"), value: address || "—" },
            { label: t("crm.field.enterprise"), value: guest.tex_enterprise || "—" },
          ]}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <h3 className="text-xs font-medium text-zinc-500">{t("crm.field.tags")}</h3>
            {tags.length ? (
              <ul className="mt-1.5 flex flex-wrap gap-1.5">
                {tags.map((tg) => (
                  <li key={tg}>
                    <Badge tone="neutral">
                      <Tag className="size-3" aria-hidden />
                      {tg}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-0.5 text-sm text-zinc-500">{t("crm.profile.no_tags")}</p>
            )}
          </div>
          <div>
            <h3 className="text-xs font-medium text-zinc-500">{t("crm.field.preferences")}</h3>
            <p className="mt-0.5 text-sm whitespace-pre-line text-zinc-900">{guest.tex_preferences || "—"}</p>
          </div>
        </div>
        {Boolean(guest.guest_notes || guest.blacklisted) && (
          <div className="grid gap-4 sm:grid-cols-2">
            {guest.guest_notes && (
              <div>
                <h3 className="text-xs font-medium text-zinc-500">{t("crm.field.notes")}</h3>
                <p className="mt-0.5 text-sm whitespace-pre-line text-zinc-900">{guest.guest_notes}</p>
              </div>
            )}
            {guest.blacklisted ? (
              <div>
                <h3 className="text-xs font-medium text-zinc-500">{t("crm.field.blacklist_reason")}</h3>
                <p className="mt-0.5 text-sm whitespace-pre-line text-rose-800">{guest.blacklist_reason || "—"}</p>
              </div>
            ) : null}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
