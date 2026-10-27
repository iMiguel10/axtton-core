import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Plus, ClipboardList } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/shared/components/EmptyState";
import { TableSkeleton } from "@/shared/components/Loading";
import { Badge } from "@/shared/components/ui/badge";
import { buttonVariants } from "@/shared/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/shared/components/ui/card";
import { Input } from "@/shared/components/ui/input";
import { errorMessage } from "@/shared/lib/errors";
import { cn } from "@/shared/lib/utils";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

import { clientName } from "../clients/clientName";
import { ordersApi } from "../orders/api";
import { isStalled, OrdersTable } from "../orders/OrderBits";
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
  const { workshopId } = useActiveWorkshop();
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
            <SearchResults result={results.data} query={q} />
          </div>
        )}
      </div>
      <Summary />
      <OpenOrders />
    </section>
  );
}

/**
 * Qué parece lo escrito, para ofrecer darlo de alta si no existe: solo cifras,
 * un teléfono; letras y cifras juntas, una matrícula; lo demás, un nombre.
 */
function guess(query: string): "phone" | "plate" | "name" {
  const compact = query.replace(/[\s.-]/g, "");
  if (/^\+?\d{6,}$/.test(compact)) return "phone";
  if (/\d/.test(compact) && /[a-z]/i.test(compact) && compact.length <= 12) return "plate";
  return "name";
}

function SearchResults({ result, query }: { result: SearchResult; query: string }) {
  const { t } = useTranslation();
  const { canManageOrders, canManageClients } = useActiveWorkshop();
  if (result.vehicles.length === 0 && result.clients.length === 0) {
    const kind = guess(query);
    // Sin resultados, lo escrito no se pierde: el alta empieza ya rellena.
    const create =
      kind === "plate"
        ? { to: `/vehicles/new?${new URLSearchParams({ plate: query })}`, label: t("home.createVehicle", { plate: query }) }
        : {
            to: `/clients/new?${new URLSearchParams({ [kind]: query })}`,
            label: t(kind === "phone" ? "home.createClientPhone" : "home.createClientName", { value: query }),
          };
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-muted-foreground">{t("home.noResults")}</p>
        {canManageClients && (
          <Link to={create.to} className={buttonVariants({ size: "sm" })}>
            <Plus />
            {create.label}
          </Link>
        )}
      </div>
    );
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
                  <Link to={`/vehicles/${vehicle.id}`} className="link tabular-nums">
                    {vehicle.plate}
                  </Link>
                  <span className="text-muted-foreground text-sm">
                    {[vehicle.make, vehicle.model].filter(Boolean).join(" ")}
                  </span>
                  {vehicle.owner && (
                    <Link to={`/clients/${vehicle.owner.id}`} className="link text-sm">
                      {clientName(t, vehicle.owner.name)}
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
                    <Link to={`/clients/${client.id}`} className="link">
                      {client.name}
                    </Link>
                    <span className="text-muted-foreground text-sm">{client.phone}</span>
                    {client.archived && <Badge variant="secondary">{t("clients.archived")}</Badge>}
                  </div>
                  {client.vehicles.length > 0 && (
                    <ul className="grid gap-1 pl-3">
                      {client.vehicles.map((vehicle) => (
                        <li key={vehicle.id} className="flex flex-wrap items-center gap-2 text-sm">
                          <Link to={`/vehicles/${vehicle.id}`} className="link tabular-nums">
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
        <Link to="/orders" className={buttonVariants({ variant: "outline", size: "sm" })}>
          {t("home.allOrders")}
        </Link>
      </CardHeader>
      <CardContent>
        {orders.isPending ? (
          <TableSkeleton rows={4} />
        ) : orders.isError ? (
          <p role="alert">{errorMessage(t, orders.error)}</p>
        ) : orders.data.length === 0 ? (
          <EmptyState compact icon={ClipboardList} title={t("orders.none")} />
        ) : (
          <OrdersTable orders={orders.data} />
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Cuatro cifras arriba (como las tarjetas de dashboard-01): lo que hay que mirar
 * al llegar al taller, cada una con su enlace. Salen de las mismas listas que la
 * pantalla ya pide: las abiertas (la primera página, hasta 50) y las pendientes
 * de cobro.
 */
function Summary() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [now] = useState(() => Date.now());
  const filters = { state: "open" as const, sort: "stalled" as const };
  const open = useQuery({
    queryKey: ["orders", workshopId, filters],
    queryFn: () => ordersApi(workshopId).list(filters),
  });
  const unpaid = useQuery({
    queryKey: ["orders", workshopId, "unpaid", "summary"],
    queryFn: () => ordersApi(workshopId).unpaid(),
  });
  const orders = open.data ?? [];
  const oldest = unpaid.data?.[0]?.days_pending;
  const cards = [
    {
      key: "open",
      value: open.data && orders.length,
      hint: t("home.cards.openHint"),
      to: "/orders",
    },
    {
      key: "stalled",
      value: open.data && orders.filter((order) => isStalled(order, now)).length,
      hint: t("home.cards.stalledHint"),
      to: "/orders",
    },
    {
      key: "ready",
      value: open.data && orders.filter((order) => order.status === "ready").length,
      hint: t("home.cards.readyHint"),
      to: "/orders",
    },
    {
      key: "unpaid",
      value: unpaid.data?.length,
      hint:
        oldest === undefined
          ? t("home.cards.unpaidNone")
          : t("home.cards.unpaidHint", { count: oldest }),
      to: "/orders/unpaid",
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">
      {cards.map((card) => (
        <Card key={card.key} className="gap-2 sm:gap-4">
          <CardHeader>
            <CardDescription>{t(`home.cards.${card.key}`)}</CardDescription>
            <CardTitle className="text-3xl font-semibold tabular-nums">
              {card.value ?? "—"}
            </CardTitle>
          </CardHeader>
          <CardFooter className="text-muted-foreground text-xs sm:text-sm">
            <Link to={card.to} className="link font-normal">
              {card.hint}
            </Link>
          </CardFooter>
        </Card>
      ))}
    </div>
  );
}
