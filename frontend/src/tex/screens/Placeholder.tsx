import { Construction } from "lucide-react"
import { Card, EmptyState, PageHeader } from "../ui"
import { useTexT } from "../i18n"

/** Temporary stand-in while an area's screens are built. */
export function Placeholder({ title }: { title: string }) {
  const { t } = useTexT()
  return (
    <>
      <PageHeader title={t(title)} />
      <Card>
        <EmptyState icon={<Construction className="size-5" />} title={t("core.placeholder.title")} description={t("core.placeholder.body")} />
      </Card>
    </>
  )
}
