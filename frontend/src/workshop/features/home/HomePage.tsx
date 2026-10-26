import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge } from "@/shared/components/ui/badge";
import { buttonVariants } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Input } from "@/shared/components/ui/input";
import { errorMessage } from "@/shared/lib/errors";
import { cn } from "@/shared/lib/utils";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

import { ordersApi } from "../orders/api";
import { OrdersTable } from "../orders/OrderBits";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { search, type SearchResult } from "./api";

/**
 * El mostrador: una sola caja para matrícula, nombre o teléfono (RF-14), porque
 * es lo que se pregunta con el cliente delante, y debajo las órdenes abiertas.
 * Abrir una orden para un cliente ya registrado lleva menos de un minuto
 * (RNF-21): matrícula, "Abrir orden", guardar.
 */
export function HomePage() {
  const { t } = useTranslation();
  const { workshopId, workshopName } = useActiveWorkshop();
  const [query, setQuery] = useState("");
  const q = useDebouncedValue(query.trim(), 250);
  const results = useQuery({
    queryKey: ["search", workshopId, q],
    queryFn: () => search(workshopId, q),
    enabled: q.length > 0,
    placeholderData: (previous) => previous,
  });

  return (
    <section className="grid gap-6">
      <div className="grid gap-3">
        <h1 className="text-2xl font-semibold">{workshopName}</h1>
        <label htmlFor="counter-search" className="text-sm font-medium">
          {t("home.searchLabel")}
        </label>
        <Input
          id="counter-search"
          type="search"
          autoFocus
          autoComplete="off"
          className="h-11 text-base md:text-base"
          placeholder={t("home.searchPlaceholder")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {q && results.isError && <p role="alert">{errorMessage(t, results.error)}</p>}
        {q && results.data && (
          <div className={cn(results.isPlaceholderData && "opacity-60")}>
            <SearchResults result={results.data} />
          </div>
        )}
      </div>
      <OpenOrders />
    </section>
  );
}

function SearchResults({ result }: { result: SearchResult }) {
  const { t } = useTranslation();
  const { canManageOrders } = useActiveWorkshop();
  if (result.vehicles.length === 0 && result.clients.length === 0) {
    return <p className="text-muted-foreground">{t("home.noResults")}</p>;
  }
  const openOrder = (vehicleId: string) =>
    canManageOrders && (
      <Link
        to={`/orders/new?vehicle=${vehicleId}`}
        className={buttonVariants({ size: "sm", variant: "outline" })}
      >
        {t("orders.new")}
      </Link>
    );

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {result.vehicles.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("home.vehicles")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-2">
              {result.vehicles.map((vehicle) => (
                <li key={vehicle.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <Link to={`/vehicles/${vehicle.id}`} className="font-mono font-medium hover:underline">
                    {vehicle.plate}
                  </Link>
                  <span className="text-muted-foreground text-sm">
                    {[vehicle.make, vehicle.model].filter(Boolean).join(" ")}
                  </span>
                  {vehicle.owner && (
                    <Link to={`/clients/${vehicle.owner.id}`} className="text-sm hover:underline">
                      {vehicle.owner.name}
                    </Link>
                  )}
                  <span className="ml-auto">{openOrder(vehicle.id)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      {result.clients.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("home.clients")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-3">
              {result.clients.map((client) => (
                <li key={client.id} className="grid gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link to={`/clients/${client.id}`} className="font-medium hover:underline">
                      {client.name}
                    </Link>
                    <span className="text-muted-foreground text-sm">{client.phone}</span>
                    {client.archived && <Badge variant="secondary">{t("clients.archived")}</Badge>}
                  </div>
                  {client.vehicles.length > 0 && (
                    <ul className="grid gap-1 pl-3">
                      {client.vehicles.map((vehicle) => (
                        <li key={vehicle.id} className="flex flex-wrap items-center gap-2 text-sm">
                          <Link to={`/vehicles/${vehicle.id}`} className="font-mono hover:underline">
                            {vehicle.plate}
                          </Link>
                          <span className="text-muted-foreground">
                            {[vehicle.make, vehicle.model].filter(Boolean).join(" ")}
                          </span>
                          <span className="ml-auto">{openOrder(vehicle.id)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/** Las órdenes abiertas, las más paradas primero (RF-24). */
function OpenOrders() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const filters = { state: "open" as const, sort: "stalled" as const };
  const orders = useQuery({
    queryKey: ["orders", workshopId, filters],
    queryFn: () => ordersApi(workshopId).list(filters),
  });
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("home.openOrders")}</CardTitle>
        <Link to="/orders" className="text-sm hover:underline">
          {t("home.allOrders")}
        </Link>
      </CardHeader>
      <CardContent>
        {orders.isPending ? (
          <p>{t("common.loading")}</p>
        ) : orders.isError ? (
          <p role="alert">{errorMessage(t, orders.error)}</p>
        ) : orders.data.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("orders.none")}</p>
        ) : (
          <OrdersTable orders={orders.data} />
        )}
      </CardContent>
    </Card>
  );
}
