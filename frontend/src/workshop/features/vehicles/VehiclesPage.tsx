import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button, buttonVariants } from "@/shared/components/ui/button";
import { Input } from "@/shared/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/components/ui/table";
import { errorMessage } from "@/shared/lib/errors";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t("vehicles.title")}</h1>
        {canManageClients && (
          <Link to="/vehicles/new" className={buttonVariants()}>
            {t("vehicles.new")}
          </Link>
        )}
      </div>
      <Input
        type="search"
        className="max-w-sm"
        aria-label={t("vehicles.search")}
        placeholder={t("vehicles.searchPlaceholder")}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {vehicles.isPending ? (
        <p>{t("common.loading")}</p>
      ) : vehicles.isError ? (
        <p role="alert">{errorMessage(t, vehicles.error)}</p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground">
          {t(q.trim() ? "vehicles.noResults" : "vehicles.empty")}
        </p>
      ) : (
        <>
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
                <TableRow key={vehicle.id}>
                  <TableCell>
                    <Link
                      to={`/vehicles/${vehicle.id}`}
                      className="font-mono font-medium hover:underline"
                    >
                      {vehicle.plate}
                    </Link>
                  </TableCell>
                  <TableCell>
                    {[vehicle.make, vehicle.model].filter(Boolean).join(" ") || "—"}
                  </TableCell>
                  <TableCell>
                    {vehicle.owner ? (
                      <Link to={`/clients/${vehicle.owner.id}`} className="hover:underline">
                        {vehicle.owner.name}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {vehicles.hasNextPage && (
            <Button
              variant="outline"
              className="justify-self-start"
              disabled={vehicles.isFetchingNextPage}
              onClick={() => void vehicles.fetchNextPage()}
            >
              {t("vehicles.loadMore")}
            </Button>
          )}
        </>
      )}
    </section>
  );
}
