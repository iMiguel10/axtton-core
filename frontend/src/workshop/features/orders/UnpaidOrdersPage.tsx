import { Wallet } from "lucide-react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/shared/components/EmptyState";
import { TableSkeleton } from "@/shared/components/Loading";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent } from "@/shared/components/ui/card";
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
import { ordersApi, PAGE_SIZE } from "./api";

/**
 * Las entregadas pendientes de cobro, la que más lleva primero (RF-29). Los días
 * los calcula el servidor en la zona del taller. El importe llegará con los
 * presupuestos (F3): hoy no hay de dónde sacarlo.
 */
export function UnpaidOrdersPage() {
  const { t } = useTranslation();
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
      <Card>
        <CardContent>
      {orders.isPending ? (
        <TableSkeleton />
      ) : orders.isError ? (
        <p role="alert">{errorMessage(t, orders.error)}</p>
      ) : rows.length === 0 ? (
        <EmptyState icon={Wallet} title={t("payment.noneUnpaid")} />
      ) : (
        <>
        <MobileCards>
          {rows.map((order) => (
            <MobileCard
              key={order.id}
              to={`/orders/${order.id}`}
              title={order.code}
              aside={<span className="text-sm font-medium tabular-nums">{t("payment.days", { count: order.days_pending })}</span>}
              lines={[
                <span key="v" className="text-foreground tabular-nums">{order.vehicle.plate}</span>,
                clientName(t, order.client.name),
              ]}
            />
          ))}
        </MobileCards>
        <div className="hidden md:block">
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
              <LinkRow key={order.id} to={`/orders/${order.id}`}>
                <TableCell>
                  <Link to={`/orders/${order.id}`} className="link tabular-nums">
                    {order.code}
                  </Link>
                </TableCell>
                <TableCell className="tabular-nums">{order.vehicle.plate}</TableCell>
                <TableCell>
                  {clientName(t, order.client.name)}
                  {order.client.phone && (
                    <span className="text-muted-foreground hidden sm:inline"> · {order.client.phone}</span>
                  )}
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  <When iso={order.delivered_at} />
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {t("payment.days", { count: order.days_pending })}
                </TableCell>
              </LinkRow>
            ))}
          </TableBody>
        </Table>
        </div>
        </>
      )}
      {orders.hasNextPage && (
        <Button
          variant="outline"
          className="mt-4"
          disabled={orders.isFetchingNextPage}
          onClick={() => void orders.fetchNextPage()}
        >
          {t("orders.loadMore")}
        </Button>
      )}
        </CardContent>
      </Card>
    </section>
  );
}
