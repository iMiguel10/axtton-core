import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ClipboardList } from "lucide-react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/shared/components/EmptyState";
import { TableSkeleton } from "@/shared/components/Loading";
import { SegmentedFilter, SwitchFilter } from "@/shared/components/filters/Filters";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader } from "@/shared/components/ui/card";
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
  const { workshopId } = useActiveWorkshop();
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
      <Card>
        <CardHeader className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <SegmentedFilter
            label={t("orders.state")}
            value={state}
            options={STATES.map((value) => ({ value, label: t(`orders.states.${value}`) }))}
            onChange={setState}
          />
          <SwitchFilter label={t("orders.mine")} checked={mine} onChange={setMine} />
          <SwitchFilter label={t("orders.stalledFirst")} checked={stalledFirst} onChange={setStalledFirst} />
        </CardHeader>
        <CardContent>
      {orders.isPending ? (
        <TableSkeleton />
      ) : orders.isError ? (
        <p role="alert">{errorMessage(t, orders.error)}</p>
      ) : rows.length === 0 ? (
        <EmptyState icon={ClipboardList} title={t(mine ? "orders.noneMine" : "orders.none")} />
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
        </CardContent>
      </Card>
    </section>
  );
}
