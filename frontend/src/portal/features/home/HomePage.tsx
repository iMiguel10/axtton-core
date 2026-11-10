import { useQuery } from "@tanstack/react-query";
import { Car } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/shared/components/EmptyState";
import { LinesSkeleton } from "@/shared/components/Loading";
import { errorMessage } from "@/shared/lib/errors";

import { ClientStatusBadge, ProgressDetails } from "../orders/ClientProgress";
import { fetchVehicles, makeAndModel, type OrderSummary } from "../orders/api";
import { usePortalMe } from "./PortalLayout";

/** El inicio: los vehículos del cliente y sus órdenes (RF-42). */
export function HomePage() {
  const { t } = useTranslation();
  const me = usePortalMe();
  const vehicles = useQuery({ queryKey: ["portal", "vehicles"], queryFn: fetchVehicles });

  return (
    <>
      <div className="grid gap-1">
        <p className="text-muted-foreground text-sm">{me.data?.workshop_name}</p>
        <h1 className="text-2xl font-semibold">
          {t("portal.home.greeting", { name: me.data?.client_name })}
        </h1>
      </div>
      {vehicles.isPending ? (
        <LinesSkeleton />
      ) : vehicles.isError ? (
        <p role="alert">{errorMessage(t, vehicles.error)}</p>
      ) : vehicles.data.length === 0 ? (
        <EmptyState
          icon={Car}
          title={t("portal.home.emptyTitle")}
          description={t("portal.home.emptyDescription")}
        />
      ) : (
        vehicles.data.map((vehicle) => (
          <section key={vehicle.plate} className="grid gap-2">
            <h2 className="font-medium">
              <span className="tabular-nums">{vehicle.plate}</span>
              {makeAndModel(vehicle) && (
                <span className="text-muted-foreground font-normal"> · {makeAndModel(vehicle)}</span>
              )}
            </h2>
            <ul className="grid gap-2">
              {vehicle.orders.map((order) => (
                <li key={order.id}>
                  <OrderCard order={order} />
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </>
  );
}

function OrderCard({ order }: { order: OrderSummary }) {
  return (
    <Link
      to={`/orders/${order.id}`}
      className="bg-card hover:bg-muted/50 grid gap-2 rounded-lg border p-4 transition-colors"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium tabular-nums">{order.code}</span>
        <ClientStatusBadge status={order.progress.status} />
      </div>
      <ProgressDetails progress={order.progress} />
    </Link>
  );
}
