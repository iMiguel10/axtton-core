import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ClipboardList } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/shared/components/EmptyState";
import { TableSkeleton } from "@/shared/components/Loading";
import { Badge } from "@/shared/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/components/ui/table";
import { LinkRow } from "@/shared/components/table/LinkRow";
import { MobileCard, MobileCards } from "@/shared/components/table/MobileCards";
import { When } from "@/shared/components/When";
import { errorMessage } from "@/shared/lib/errors";

import { clientName } from "../clients/clientName";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { ordersApi, STALLED_DAYS, type Order, type OrderFilters, type Status } from "./api";

const CLOSED: Status[] = ["delivered", "cancelled"];

// Clases enteras, no compuestas: Tailwind solo genera las que ve escritas.
const STATUS_COLORS: Record<Status, string> = {
  received: "bg-status-received/12 text-status-received border-status-received/25",
  diagnosing: "bg-status-diagnosing/12 text-status-diagnosing border-status-diagnosing/25",
  pending_approval:
    "bg-status-pending-approval/12 text-status-pending-approval border-status-pending-approval/25",
  approved: "bg-status-approved/12 text-status-approved border-status-approved/25",
  in_repair: "bg-status-in-repair/12 text-status-in-repair border-status-in-repair/25",
  waiting_parts: "bg-status-waiting-parts/12 text-status-waiting-parts border-status-waiting-parts/25",
  ready: "bg-status-ready/12 text-status-ready border-status-ready/25",
  delivered: "bg-status-delivered/12 text-status-delivered border-status-delivered/25",
  cancelled: "bg-status-cancelled/12 text-status-cancelled border-status-cancelled/25",
};

/**
 * El estado con su color (tokens --status-* de global.css) y un punto del mismo
 * color. El color ayuda a distinguirlos de un vistazo; la etiqueta es la que dice
 * el estado, para quien no distingue colores.
 */
export function StatusBadge({ status, unrepaired }: { status: Status; unrepaired?: boolean }) {
  const { t } = useTranslation();
  return (
    <Badge variant="outline" className={STATUS_COLORS[status]}>
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {t(`orders.statuses.${status}`)}
      {unrepaired && ` · ${t("orders.unrepaired")}`}
    </Badge>
  );
}

/** Abierta y sin actividad desde hace días (RF-24). */
export function isStalled(order: Order, now = Date.now()): boolean {
  if (CLOSED.includes(order.status)) return false;
  return now - new Date(order.last_activity_at).getTime() > STALLED_DAYS * 86_400_000;
}

/** Tabla de órdenes, para el listado y para las fichas de vehículo y cliente. */
export function OrdersTable({
  orders,
  show = { vehicle: true, client: true },
}: {
  orders: Order[];
  show?: { vehicle?: boolean; client?: boolean };
}) {
  const { t } = useTranslation();
  // "Ahora" se fija al montar: calcularlo en cada render lo haría impuro.
  const [now] = useState(() => Date.now());
  return (
    <>
    <MobileCards>
      {orders.map((order) => (
        <MobileCard
          key={order.id}
          to={`/orders/${order.id}`}
          className={isStalled(order, now) ? "border-destructive/30 bg-destructive/5" : undefined}
          title={order.code}
          aside={<StatusBadge status={order.status} unrepaired={order.unrepaired} />}
          lines={[
            show.vehicle && (
              <>
                <span className="text-foreground tabular-nums">{order.vehicle.plate}</span>
                {order.vehicle.make && ` · ${[order.vehicle.make, order.vehicle.model].filter(Boolean).join(" ")}`}
              </>
            ),
            show.client && clientName(t, order.client.name),
            order.expected_delivery_at && (
              <>
                {t("orders.expectedDelivery")}: <When iso={order.expected_delivery_at} />
              </>
            ),
          ]}
        />
      ))}
    </MobileCards>
    <div className="hidden md:block">
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("orders.code")}</TableHead>
          <TableHead>{t("orders.status")}</TableHead>
          {show.vehicle && <TableHead>{t("orders.vehicle")}</TableHead>}
          {show.client && (
            <TableHead className="hidden md:table-cell">{t("orders.client")}</TableHead>
          )}
          <TableHead className="hidden md:table-cell">{t("orders.responsible")}</TableHead>
          <TableHead className="hidden lg:table-cell">{t("orders.expectedDelivery")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {orders.map((order) => {
          const stalled = isStalled(order, now);
          return (
            <LinkRow key={order.id} to={`/orders/${order.id}`} className={stalled ? "bg-destructive/5" : undefined}>
              <TableCell>
                <Link to={`/orders/${order.id}`} className="link tabular-nums">
                  {order.code}
                </Link>
                {stalled && (
                  <Badge variant="destructive" className="ml-2">
                    {t("orders.stalled")}
                  </Badge>
                )}
              </TableCell>
              <TableCell>
                <StatusBadge status={order.status} unrepaired={order.unrepaired} />
              </TableCell>
              {show.vehicle && (
                <TableCell>
                  <span className="tabular-nums">{order.vehicle.plate}</span>
                  {order.vehicle.make && (
                    <span className="text-muted-foreground hidden sm:inline">
                      {" · "}
                      {[order.vehicle.make, order.vehicle.model].filter(Boolean).join(" ")}
                    </span>
                  )}
                </TableCell>
              )}
              {show.client && (
                <TableCell className="hidden md:table-cell">{clientName(t, order.client.name)}</TableCell>
              )}
              <TableCell className="hidden md:table-cell">
                {order.responsible?.name ?? "—"}
              </TableCell>
              <TableCell className="hidden lg:table-cell">
                {order.expected_delivery_at ? <When iso={order.expected_delivery_at} /> : "—"}
              </TableCell>
            </LinkRow>
          );
        })}
      </TableBody>
    </Table>
    </div>
    </>
  );
}

/** Las órdenes de un vehículo o de un cliente, en su ficha (RF-13). */
export function RelatedOrders({
  filters,
  show,
}: {
  filters: Pick<OrderFilters, "vehicleId" | "clientId">;
  show: { vehicle?: boolean; client?: boolean };
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const orders = useQuery({
    queryKey: ["orders", workshopId, { state: "all", ...filters }],
    queryFn: () => ordersApi(workshopId).list({ state: "all", ...filters }),
  });
  if (orders.isPending) return <TableSkeleton rows={3} />;
  if (orders.isError) return <p role="alert">{errorMessage(t, orders.error)}</p>;
  if (orders.data.length === 0) {
    return <EmptyState compact icon={ClipboardList} title={t("orders.none")} />;
  }
  return <OrdersTable orders={orders.data} show={show} />;
}
