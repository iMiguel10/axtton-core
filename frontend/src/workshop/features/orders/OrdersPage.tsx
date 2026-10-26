import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button, buttonVariants } from "@/shared/components/ui/button";
import { errorMessage } from "@/shared/lib/errors";
import { cn } from "@/shared/lib/utils";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { ordersApi, PAGE_SIZE, type OrderFilters } from "./api";
import { OrdersTable } from "./OrderBits";

const STATES: OrderFilters["state"][] = ["open", "closed", "all"];

/** Órdenes del taller activo (RF-24): las abiertas por defecto, "mis órdenes" y
 * las que llevan más tiempo paradas destacadas. */
export function OrdersPage() {
  const { t } = useTranslation();
  const { workshopId, canManageOrders } = useActiveWorkshop();
  const [state, setState] = useState<OrderFilters["state"]>("open");
  const [mine, setMine] = useState(false);
  const [stalledFirst, setStalledFirst] = useState(false);
  const filters: OrderFilters = { state, mine, sort: stalledFirst ? "stalled" : "recent" };

  const orders = useInfiniteQuery({
    queryKey: ["orders", workshopId, filters],
    queryFn: ({ pageParam }) => ordersApi(workshopId).list(filters, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.length < PAGE_SIZE ? undefined : pages.length * PAGE_SIZE,
    placeholderData: (previous) => previous,
  });
  const rows = orders.data?.pages.flat() ?? [];

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t("orders.title")}</h1>
        {canManageOrders && (
          <Link to="/orders/new" className={buttonVariants()}>
            {t("orders.new")}
          </Link>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <div role="group" aria-label={t("orders.state")} className="flex gap-1">
          {STATES.map((value) => (
            <Button
              key={value}
              size="sm"
              variant={state === value ? "default" : "outline"}
              aria-pressed={state === value}
              onClick={() => setState(value)}
            >
              {t(`orders.states.${value}`)}
            </Button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
          {t("orders.mine")}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={stalledFirst}
            onChange={(e) => setStalledFirst(e.target.checked)}
          />
          {t("orders.stalledFirst")}
        </label>
      </div>
      {orders.isPending ? (
        <p>{t("common.loading")}</p>
      ) : orders.isError ? (
        <p role="alert">{errorMessage(t, orders.error)}</p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground">{t(mine ? "orders.noneMine" : "orders.none")}</p>
      ) : (
        <div className={cn(orders.isPlaceholderData && "opacity-60")}>
          <OrdersTable orders={rows} />
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
        </div>
      )}
    </section>
  );
}
