import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button } from "@/shared/components/ui/button";
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
import { ordersApi, PAGE_SIZE } from "./api";
import { formatDateTime } from "./OrderBits";

/**
 * Las entregadas pendientes de cobro, la que más lleva primero (RF-29). Los días
 * los calcula el servidor en la zona del taller. El importe llegará con los
 * presupuestos (F3): hoy no hay de dónde sacarlo.
 */
export function UnpaidOrdersPage() {
  const { t, i18n } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const orders = useInfiniteQuery({
    queryKey: ["orders", workshopId, "unpaid"],
    queryFn: ({ pageParam }) => ordersApi(workshopId).unpaid(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.length < PAGE_SIZE ? undefined : pages.length * PAGE_SIZE,
  });
  const rows = orders.data?.pages.flat() ?? [];

  return (
    <section className="grid gap-4">
      <Link to="/orders" className="text-muted-foreground text-sm hover:underline">
        ← {t("orders.backToList")}
      </Link>
      <h1 className="text-2xl font-semibold">{t("payment.unpaidTitle")}</h1>
      {orders.isPending ? (
        <p>{t("common.loading")}</p>
      ) : orders.isError ? (
        <p role="alert">{errorMessage(t, orders.error)}</p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground">{t("payment.noneUnpaid")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("orders.code")}</TableHead>
              <TableHead>{t("orders.vehicle")}</TableHead>
              <TableHead>{t("orders.client")}</TableHead>
              <TableHead className="hidden md:table-cell">{t("payment.deliveredAt")}</TableHead>
              <TableHead className="text-right">{t("payment.daysPending")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((order) => (
              <TableRow key={order.id}>
                <TableCell>
                  <Link to={`/orders/${order.id}`} className="font-mono font-medium hover:underline">
                    {order.code}
                  </Link>
                </TableCell>
                <TableCell className="font-mono">{order.vehicle.plate}</TableCell>
                <TableCell>
                  {clientName(t, order.client.name)}
                  {order.client.phone && (
                    <span className="text-muted-foreground hidden sm:inline"> · {order.client.phone}</span>
                  )}
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  {formatDateTime(order.delivered_at, i18n.language)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {t("payment.days", { count: order.days_pending })}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {orders.hasNextPage && (
        <div>
          <Button variant="outline" disabled={orders.isFetchingNextPage} onClick={() => void orders.fetchNextPage()}>
            {t("orders.loadMore")}
          </Button>
        </div>
      )}
    </section>
  );
}
