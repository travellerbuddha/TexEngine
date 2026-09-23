import { useState } from "react"
import { Link2, Pencil, Plus } from "lucide-react"
import { num } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, CardHeader, DataTable, EmptyState, ErrorState, IconButton } from "../../../ui"
import { mappingCodes, useLookupNames } from "./common"
import { MappingDrawer } from "./MappingDrawer"
import type { Mapping, TabProps } from "./types"

/** Channel room/rate codes ↔ what TEX sells under them. A mapping is switched off rather
 * than deleted: its ARI jobs and history keep pointing at it. */
export function MappingsTab({ connection, lookups, mappings, canManage, onChanged }: TabProps) {
  const { t } = useTexT()
  const names = useLookupNames(lookups.data)
  const [editing, setEditing] = useState<Mapping | "new" | null>(null)
  const changed = () => {
    mappings.reload()
    onChanged()
  }

  const addButton = canManage ? (
    <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setEditing("new")} disabled={!lookups.data}>
      {t("connect.channels.mappings.add")}
    </Button>
  ) : undefined

  const enabledBadge = (m: Mapping) => (m.enabled ? <Badge tone="success">{t("connect.enabled")}</Badge> : <Badge tone="neutral">{t("connect.disabled")}</Badge>)

  return (
    <>
      <CardHeader title={t("connect.channels.mappings.title")} description={t("connect.channels.mappings.hint")} actions={addButton} />
      {mappings.error || lookups.error ? (
        <ErrorState error={(mappings.error ?? lookups.error)!} onRetry={mappings.error ? mappings.reload : lookups.reload} />
      ) : (
        <DataTable<Mapping>
          caption={t("connect.channels.mappings.title")}
          rows={mappings.data}
          loading={mappings.loading}
          rowKey={(m) => m.name}
          onRowClick={canManage ? (m) => setEditing(m) : undefined}
          initialSort={{ key: "codes", dir: "asc" }}
          empty={
            <EmptyState
              icon={<Link2 className="size-5" />}
              title={t("connect.channels.mappings.empty")}
              description={t("connect.channels.mappings.empty_hint")}
              action={addButton}
            />
          }
          columns={[
            {
              key: "codes",
              header: t("connect.channels.mapping.codes"),
              sortValue: (m) => mappingCodes(m),
              cell: (m) => (
                <span className="block min-w-0">
                  <span className="font-mono text-xs font-medium break-all text-zinc-900 sm:break-normal sm:whitespace-nowrap">{mappingCodes(m)}</span>
                  <span className="block text-xs text-zinc-500">
                    → {names.roomType(m.room_type)}
                    {/* phones: board and a switched-off state live here (their columns are hidden) */}
                    <span className="sm:hidden"> · {m.board}</span>
                  </span>
                  {!m.enabled && <span className="mt-1 block sm:hidden">{enabledBadge(m)}</span>}
                </span>
              ),
            },
            {
              key: "board",
              header: t("connect.channels.mapping.board"),
              hideBelow: "sm",
              sortValue: (m) => m.board,
              cell: (m) => <span className="font-mono text-xs">{m.board}</span>,
            },
            {
              key: "rate_plan",
              header: t("connect.channels.mapping.rate_plan"),
              hideBelow: "md",
              cell: (m) => (m.rate_plan ? names.ratePlan(m.rate_plan) : <span className="text-zinc-500">—</span>),
            },
            { key: "market", header: t("connect.channels.mapping.market"), hideBelow: "md", sortValue: (m) => names.market(m.market), cell: (m) => names.market(m.market) },
            { key: "channel", header: t("connect.channels.mapping.sales_channel"), hideBelow: "lg", cell: (m) => names.channel(m.sales_channel) },
            { key: "currency", header: t("connect.channels.mapping.currency"), hideBelow: "sm", cell: (m) => m.sell_currency },
            {
              key: "contract",
              header: t("connect.channels.mapping.contract"),
              hideBelow: "lg",
              cell: (m) => (m.contract ? names.contract(m.contract) : <span className="text-zinc-500">{t("connect.channels.mapping.contract_auto")}</span>),
            },
            {
              key: "occupancies",
              header: t("connect.channels.mapping.occupancies"),
              hideBelow: "md",
              cell: (m) => <span className="whitespace-nowrap tabular-nums">{(m.occupancies || "2").split(",").join(", ")}</span>,
            },
            { key: "horizon", header: t("connect.channels.mapping.horizon"), align: "right", hideBelow: "md", sortValue: (m) => m.horizon_days ?? 0, cell: (m) => num(m.horizon_days ?? 90) },
            { key: "enabled", header: t("connect.field.status"), hideBelow: "sm", cell: enabledBadge },
            ...(canManage
              ? [
                  {
                    key: "actions",
                    header: <span className="sr-only">{t("connect.outbox.col.actions")}</span>,
                    align: "right" as const,
                    cell: (m: Mapping) => (
                      <IconButton
                        size="sm"
                        label={t("connect.channels.mappings.edit_named", { codes: mappingCodes(m) })}
                        icon={<Pencil className="size-4" />}
                        onKeyDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation()
                          setEditing(m)
                        }}
                      />
                    ),
                  },
                ]
              : []),
          ]}
        />
      )}
      {lookups.data && (
        <MappingDrawer
          mapping={editing}
          connection={connection}
          lookups={lookups.data}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            changed()
          }}
        />
      )}
    </>
  )
}
