import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ClipboardList } from "lucide-react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/shared/components/EmptyState";
import { TableSkeleton } from "@/shared/components/Loading";
import { SegmentedFilter, SelectFilter, SwitchFilter } from "@/shared/components/filters/Filters";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";
import { cn } from "@/shared/lib/utils";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import {
  DUES,
  fetchStaff,
  ordersApi,
  PAGE_SIZE,
  SORTS,
  STATUSES,
  type Due,
  type OrderFilters,
  type Sort,
  type Status,
} from "./api";
import { OrdersTable } from "./OrderBits";

const STATES: OrderFilters["state"][] = ["open", "closed", "all"];
const CLOSED: Status[] = ["delivered", "cancelled"];

/** Los estados que se pueden elegir dentro de "abiertas", "cerradas" o "todas". */
function statusesOf(state: OrderFilters["state"]): Status[] {
  if (state === "all") return [...STATUSES];
  return STATUSES.filter((status) => CLOSED.includes(status) === (state === "closed"));
}

/** Órdenes del taller activo (RF-24): las abiertas por defecto, filtrables por
 * estado, responsable y fecha prevista, "mis órdenes" y las que llevan más
 * tiempo paradas destacadas. */
export function OrdersPage() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [state, setState] = useState<OrderFilters["state"]>("open");
  const [status, setStatus] = useState<Status | "">("");
  const [responsibleId, setResponsibleId] = useState("");
  const [due, setDue] = useState<Due | "">("");
  const [mine, setMine] = useState(false);
  const [sort, setSort] = useState<Sort>("recent");
  const filters: OrderFilters = {
    state,
    status: status || undefined,
    responsibleId: responsibleId || undefined,
    due: due || undefined,
    mine,
    sort,
  };
  const filtered = Boolean(status || responsibleId || due || mine);
  const clear = () => {
    setStatus("");
    setResponsibleId("");
    setDue("");
    setMine(false);
  };

  const staff = useQuery({ queryKey: ["staff", workshopId], queryFn: () => fetchStaff(workshopId) });
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
        <CardHeader className="grid gap-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <SegmentedFilter
              label={t("orders.state")}
              value={state}
              options={STATES.map((value) => ({ value, label: t(`orders.states.${value}`) }))}
              onChange={(value) => {
                setState(value);
                // Un estado que no es del grupo nuevo dejaría la lista vacía.
                if (status && !statusesOf(value).includes(status)) setStatus("");
              }}
            />
            <SwitchFilter label={t("orders.mine")} checked={mine} onChange={setMine} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SelectFilter
              label={t("orders.status")}
              any={t("orders.filters.anyStatus")}
              value={status}
              options={statusesOf(state).map((value) => ({ value, label: t(`orders.statuses.${value}`) }))}
              onChange={setStatus}
            />
            <SelectFilter
              label={t("orders.responsible")}
              any={t("orders.filters.anyResponsible")}
              value={responsibleId}
              options={(staff.data ?? []).map((member) => ({ value: member.id, label: member.name }))}
              onChange={setResponsibleId}
            />
            <SelectFilter
              label={t("orders.expectedDelivery")}
              any={t("orders.filters.anyDue")}
              value={due}
              options={DUES.map((value) => ({ value, label: t(`orders.filters.dues.${value}`) }))}
              onChange={setDue}
            />
            <SelectFilter
              label={t("orders.filters.sort")}
              any={t("orders.filters.sorts.recent")}
              // "Las más recientes" es el orden por defecto: hace de "cualquiera".
              value={sort === "recent" ? "" : sort}
              options={SORTS.filter((value) => value !== "recent").map((value) => ({
                value,
                label: t(`orders.filters.sorts.${value}`),
              }))}
              onChange={(value) => setSort(value || "recent")}
            />
            {filtered && (
              <Button variant="ghost" size="sm" onClick={clear}>
                {t("orders.filters.clear")}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {/* Al cambiar de filtro se ven los datos del anterior mientras llegan
              los nuevos; si estaban vacíos, "no hay" sería mentira: se espera. */}
          {orders.isPending || (orders.isPlaceholderData && rows.length === 0) ? (
            <TableSkeleton />
          ) : orders.isError ? (
            <p role="alert">{errorMessage(t, orders.error)}</p>
          ) : rows.length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title={t(mine && !status && !responsibleId && !due ? "orders.noneMine" : filtered ? "orders.noneFiltered" : "orders.none")}
              action={
                filtered ? (
                  <Button variant="outline" onClick={clear}>
                    {t("orders.filters.clear")}
                  </Button>
                ) : undefined
              }
            />
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
