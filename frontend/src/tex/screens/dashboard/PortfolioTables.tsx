import { useMemo } from "react"
import { Link } from "react-router-dom"
import { useSession } from "../../lib/session"
import { num } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Card, CardHeader, DataTable, EmptyState, type Column } from "../../ui"
import { AmountStack } from "./PortfolioKpis"
import {
  HOTEL_DASHBOARD,
  rankBy,
  useSelectHotel,
  type Amounts,
  type HotelFigures,
  type MarketRow,
  type PortfolioData,
  type RoomRow,
} from "./portfolio"

/** A count with its money (per currency) underneath. */
function CountWithAmounts({ count, amounts, first }: { count: number; amounts: Amounts; first?: string }) {
  return (
    <span className="inline-flex flex-col items-end">
      <span>{num(count)}</span>
      {count > 0 && <AmountStack amounts={amounts} first={first} align="end" className="text-xs text-zinc-500" />}
    </span>
  )
}

type HotelMoney = "booking_value" | "direct_value" | "call_centre_value"

/** One row per hotel of the scope; the hotel name opens that hotel's own dashboard. */
export function PortfolioHotels({ data, currency }: { data: PortfolioData | undefined; currency?: string }) {
  const { t } = useTexT()
  const select = useSelectHotel()
  const rows = data?.hotels
  // money columns sort by the chosen currency, compared as exact decimals
  const ranks = useMemo(() => {
    const out = {} as Record<HotelMoney, Map<string, number>>
    for (const k of ["booking_value", "direct_value", "call_centre_value"] as HotelMoney[])
      out[k] = rankBy(rows ?? [], (h) => h.hotel, (h) => (currency ? h[k][currency] : undefined))
    return out
  }, [rows, currency])
  const moneyCol = (key: HotelMoney, header: string, hideBelow?: Column<HotelFigures>["hideBelow"]): Column<HotelFigures> => ({
    key,
    header,
    align: "right",
    hideBelow,
    sortValue: (h) => ranks[key].get(h.hotel) ?? 0,
    cell: (h) => <AmountStack amounts={h[key]} first={currency} align="end" />,
  })
  const countCol = (
    key: "cancellations" | "pending_payment" | "open_balances" | "abandoned",
    amounts: (h: HotelFigures) => Amounts,
    header: string,
  ): Column<HotelFigures> => ({
    key,
    header,
    align: "right",
    hideBelow: "lg",
    sortValue: (h) => h[key],
    cell: (h) => <CountWithAmounts count={h[key]} amounts={amounts(h)} first={currency} />,
  })
  const columns: Column<HotelFigures>[] = [
    {
      key: "hotel",
      header: t("dash.pf.col.hotel"),
      sortValue: (h) => h.hotel_name,
      cell: (h) => (
        <Link
          to={HOTEL_DASHBOARD}
          onClick={select(h.hotel)}
          className="font-medium text-tex-700 underline-offset-2 hover:underline focus-visible:underline"
        >
          {h.hotel_name}
          <span className="sr-only"> – {t("dash.pf.open_dashboard")}</span>
        </Link>
      ),
    },
    {
      key: "sold",
      header: t("dash.pf.col.sold"),
      align: "right",
      sortValue: (h) => h.sold,
      cell: (h) => (
        <span className="inline-flex flex-col items-end">
          <span>{num(h.sold)}</span>
          {h.sold_today > 0 && <span className="text-xs whitespace-nowrap text-zinc-500">{t("dash.pf.n_today", { count: h.sold_today })}</span>}
        </span>
      ),
    },
    moneyCol("booking_value", t("dash.pf.col.booking_value")),
    moneyCol("direct_value", t("dash.pf.col.direct"), "md"),
    moneyCol("call_centre_value", t("dash.pf.col.call_centre"), "md"),
    countCol("cancellations", (h) => h.cancelled_value, t("dash.pf.col.cancellations")),
    countCol("pending_payment", (h) => h.pending_payment_value, t("dash.pf.col.pending_payment")),
    countCol("open_balances", (h) => h.open_balance_value, t("dash.pf.col.open_balances")),
    countCol("abandoned", (h) => h.abandoned_value, t("dash.pf.col.abandoned")),
    {
      key: "alerts",
      header: t("dash.pf.col.alerts"),
      align: "right",
      hideBelow: "sm",
      sortValue: (h) => h.inventory_alerts + h.restriction_alerts,
      cell: (h) =>
        h.inventory_alerts || h.restriction_alerts ? (
          <span className="inline-flex flex-col items-end gap-1">
            {h.inventory_alerts > 0 && <Badge tone="warning">{t("dash.pf.n_inventory_alerts", { count: h.inventory_alerts })}</Badge>}
            {h.restriction_alerts > 0 && <Badge tone="info">{t("dash.pf.n_restriction_alerts", { count: h.restriction_alerts })}</Badge>}
          </span>
        ) : (
          <span className="text-zinc-400">—</span>
        ),
    },
  ]
  return (
    <Card>
      <CardHeader title={t("dash.pf.hotels")} description={t("dash.pf.hotels_hint")} />
      <DataTable<HotelFigures>
        caption={t("dash.pf.hotels")}
        rows={rows}
        loading={!data}
        rowKey={(h) => h.hotel}
        initialSort={{ key: "sold", dir: "desc" }}
        empty={<EmptyState title={t("dash.pf.no_hotels")} />}
        columns={columns}
      />
    </Card>
  )
}

/** Markets by bookings sold in the window (the server sends the top 20). */
export function PortfolioMarkets({ data, currency }: { data: PortfolioData | undefined; currency?: string }) {
  const { t } = useTexT()
  const { boot } = useSession()
  const rows = data?.markets
  const rank = useMemo(() => rankBy(rows ?? [], (m) => m.market, (m) => (currency ? m.value[currency] : undefined)), [rows, currency])
  const name = (m: string) =>
    !m || m === "—" ? t("dash.pf.no_market") : (boot.markets.find((x) => x.name === m)?.market_name ?? m)
  return (
    <Card>
      <CardHeader title={t("dash.pf.markets")} description={t("dash.pf.markets_hint", { count: 20 })} />
      <DataTable<MarketRow>
        caption={t("dash.pf.markets")}
        rows={rows}
        loading={!data}
        dense
        rowKey={(m) => m.market}
        initialSort={{ key: "count", dir: "desc" }}
        empty={<EmptyState title={t("dash.pf.no_sales")} />}
        columns={[
          { key: "market", header: t("dash.pf.col.market"), sortValue: (m) => name(m.market), cell: (m) => name(m.market) },
          { key: "count", header: t("dash.col.bookings"), align: "right", sortValue: (m) => m.count, cell: (m) => num(m.count) },
          {
            key: "value",
            header: t("dash.pf.col.booking_value"),
            align: "right",
            sortValue: (m) => rank.get(m.market) ?? 0,
            cell: (m) => <AmountStack amounts={m.value} first={currency} align="end" />,
          },
        ]}
      />
    </Card>
  )
}

/** Room types by room nights sold in the window (the server sends the top 20). */
export function PortfolioRooms({ data, currency }: { data: PortfolioData | undefined; currency?: string }) {
  const { t } = useTexT()
  const rows = data?.rooms
  const rank = useMemo(() => rankBy(rows ?? [], (r) => r.room_type, (r) => (currency ? r.value[currency] : undefined)), [rows, currency])
  return (
    <Card>
      <CardHeader title={t("dash.pf.rooms")} description={t("dash.pf.rooms_hint", { count: 20 })} />
      <DataTable<RoomRow>
        caption={t("dash.pf.rooms")}
        rows={rows}
        loading={!data}
        dense
        rowKey={(r) => r.room_type}
        initialSort={{ key: "nights", dir: "desc" }}
        empty={<EmptyState title={t("dash.pf.no_sales")} />}
        columns={[
          {
            key: "room",
            header: t("dash.pf.col.room_type"),
            sortValue: (r) => r.room_type_name,
            cell: (r) => (
              <span className="flex min-w-0 flex-col">
                <span className="font-medium text-zinc-900">{r.room_type_name}</span>
                {r.hotel_name && <span className="text-xs text-zinc-500">{r.hotel_name}</span>}
              </span>
            ),
          },
          { key: "count", header: t("dash.col.bookings"), align: "right", hideBelow: "sm", sortValue: (r) => r.count, cell: (r) => num(r.count) },
          { key: "nights", header: t("dash.col.room_nights"), align: "right", sortValue: (r) => r.nights, cell: (r) => num(r.nights) },
          {
            key: "value",
            header: t("dash.pf.col.booking_value"),
            align: "right",
            sortValue: (r) => rank.get(r.room_type) ?? 0,
            cell: (r) => <AmountStack amounts={r.value} first={currency} align="end" />,
          },
        ]}
      />
    </Card>
  )
}
