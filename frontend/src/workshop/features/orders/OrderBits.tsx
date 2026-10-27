import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge } from "@/shared/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/components/ui/table";
import { errorMessage } from "@/shared/lib/errors";

import { clientName } from "../clients/clientName";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { ordersApi, STALLED_DAYS, type Order, type OrderFilters, type Status } from "./api";

const CLOSED: Status[] = ["delivered", "cancelled"];

export function StatusBadge({ status, unrepaired }: { status: Status; unrepaired?: boolean }) {
  const { t } = useTranslation();
  const variant =
    status === "ready" ? "success" : CLOSED.includes(status) ? "secondary" : "outline";
  return (
    <Badge variant={variant}>
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

export function formatDateTime(iso: string | null, language: string): string | null {
  return iso
    ? new Date(iso).toLocaleString(language, { dateStyle: "short", timeStyle: "short" })
    : null;
}

/** Tabla de órdenes, para el listado y para las fichas de vehículo y cliente. */
export function OrdersTable({
  orders,
  show = { vehicle: true, client: true },
}: {
  orders: Order[];
  show?: { vehicle?: boolean; client?: boolean };
}) {
  const { t, i18n } = useTranslation();
  // "Ahora" se fija al montar: calcularlo en cada render lo haría impuro.
  const [now] = useState(() => Date.now());
  return (
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
            <TableRow key={order.id} className={stalled ? "bg-destructive/5" : undefined}>
              <TableCell>
                <Link to={`/orders/${order.id}`} className="font-mono font-medium hover:underline">
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
                  <span className="font-mono">{order.vehicle.plate}</span>
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
                {formatDateTime(order.expected_delivery_at, i18n.language) ?? "—"}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
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
  if (orders.isPending) return <p>{t("common.loading")}</p>;
  if (orders.isError) return <p role="alert">{errorMessage(t, orders.error)}</p>;
  if (orders.data.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("orders.none")}</p>;
  }
  return <OrdersTable orders={orders.data} show={show} />;
}
