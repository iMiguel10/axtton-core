import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Car, SearchX } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/shared/components/EmptyState";
import { TableSkeleton } from "@/shared/components/Loading";
import { SearchInput } from "@/shared/components/filters/Filters";
import { Button, buttonVariants } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader } from "@/shared/components/ui/card";
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
import { errorMessage } from "@/shared/lib/errors";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

import { clientName } from "../clients/clientName";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { vehiclesApi, PAGE_SIZE } from "./api";

/** Vehículos del taller activo con su titular actual (RF-11). */
export function VehiclesPage() {
  const { t } = useTranslation();
  const { workshopId, canManageClients } = useActiveWorkshop();
  const api = vehiclesApi(workshopId);
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search);

  const vehicles = useInfiniteQuery({
    queryKey: ["vehicles", workshopId, { q }],
    queryFn: ({ pageParam }) => api.list({ q }, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.length < PAGE_SIZE ? undefined : pages.length * PAGE_SIZE,
    placeholderData: (previous) => previous,
  });
  const rows = vehicles.data?.pages.flat() ?? [];

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {canManageClients && (
          <Link to="/vehicles/new" className={buttonVariants()}>
            {t("vehicles.new")}
          </Link>
        )}
      </div>
      <Card>
        <CardHeader>
          <SearchInput
            aria-label={t("vehicles.search")}
            placeholder={t("vehicles.searchPlaceholder")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </CardHeader>
        <CardContent>
      {vehicles.isPending ? (
        <TableSkeleton />
      ) : vehicles.isError ? (
        <p role="alert">{errorMessage(t, vehicles.error)}</p>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={q.trim() ? SearchX : Car}
          title={t(q.trim() ? "vehicles.noResults" : "vehicles.empty")}
          action={
            canManageClients && !q.trim() && (
              <Link to="/vehicles/new" className={buttonVariants({ size: "sm" })}>
                {t("vehicles.new")}
              </Link>
            )
          }
        />
      ) : (
        <>
          <MobileCards>
            {rows.map((vehicle) => (
              <MobileCard
                key={vehicle.id}
                to={`/vehicles/${vehicle.id}`}
                title={vehicle.plate}
                lines={[
                  [vehicle.make, vehicle.model].filter(Boolean).join(" "),
                  vehicle.owner && clientName(t, vehicle.owner.name),
                ]}
              />
            ))}
          </MobileCards>
          <div className="hidden md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("vehicles.plate")}</TableHead>
                <TableHead>{t("vehicles.makeModel")}</TableHead>
                <TableHead>{t("vehicles.owner")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((vehicle) => (
                <LinkRow key={vehicle.id} to={`/vehicles/${vehicle.id}`}>
                  <TableCell>
                    <Link
                      to={`/vehicles/${vehicle.id}`}
                      className="link tabular-nums"
                    >
                      {vehicle.plate}
                    </Link>
                  </TableCell>
                  <TableCell>
                    {[vehicle.make, vehicle.model].filter(Boolean).join(" ") || "—"}
                  </TableCell>
                  <TableCell>
                    {vehicle.owner ? (
                      <Link to={`/clients/${vehicle.owner.id}`} className="link">
                        {clientName(t, vehicle.owner.name)}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                </LinkRow>
              ))}
            </TableBody>
          </Table>
          </div>
          {vehicles.hasNextPage && (
            <Button
              variant="outline"
              className="mt-4"
              disabled={vehicles.isFetchingNextPage}
              onClick={() => void vehicles.fetchNextPage()}
            >
              {t("vehicles.loadMore")}
            </Button>
          )}
        </>
      )}
        </CardContent>
      </Card>
    </section>
  );
}
