import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge } from "@/shared/components/ui/badge";
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
import { clientsApi, PAGE_SIZE } from "./api";

/** Clientes del taller activo (RF-10). Los ve todo el personal; crearlos, solo
 * quien puede gestionarlos. */
export function ClientsPage() {
  const { t } = useTranslation();
  const { workshopId, canManageClients } = useActiveWorkshop();
  const api = clientsApi(workshopId);
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const filters = { q: useDebouncedValue(search), archived };

  // El taller va en la clave: al cambiar de taller nunca se enseña lo del anterior.
  const clients = useInfiniteQuery({
    queryKey: ["clients", workshopId, filters],
    queryFn: ({ pageParam }) => api.list(filters, pageParam),
    initialPageParam: 0,
    // Una página corta es la última.
    getNextPageParam: (last, pages) =>
      last.length < PAGE_SIZE ? undefined : pages.length * PAGE_SIZE,
    // Mientras llega la búsqueda nueva, se sigue viendo la anterior.
    placeholderData: (previous) => previous,
  });
  const rows = clients.data?.pages.flat() ?? [];

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t("clients.title")}</h1>
        {canManageClients && (
          // Un enlace con aspecto de botón: lleva a otra pantalla, no hace nada aquí.
          <Link to="/clients/new" className={buttonVariants()}>
            {t("clients.new")}
          </Link>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <Input
          type="search"
          className="max-w-sm"
          aria-label={t("clients.search")}
          placeholder={t("clients.searchPlaceholder")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={archived}
            onChange={(event) => setArchived(event.target.checked)}
          />
          {t("clients.showArchived")}
        </label>
      </div>
      {clients.isPending ? (
        <p>{t("common.loading")}</p>
      ) : clients.isError ? (
        <p role="alert">{errorMessage(t, clients.error)}</p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground">
          {t(filters.q ? "clients.noResults" : archived ? "clients.noArchived" : "clients.empty")}
        </p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("clients.name")}</TableHead>
                <TableHead>{t("clients.phone")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("clients.email")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((client) => (
                <TableRow key={client.id}>
                  <TableCell>
                    <Link to={`/clients/${client.id}`} className="font-medium hover:underline">
                      {client.name}
                    </Link>
                    {client.kind === "company" && (
                      <Badge variant="outline" className="ml-2">
                        {t("clients.kinds.company")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>{client.phone}</TableCell>
                  <TableCell className="hidden md:table-cell">{client.email ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {clients.hasNextPage && (
            <Button
              variant="outline"
              className="justify-self-start"
              disabled={clients.isFetchingNextPage}
              onClick={() => void clients.fetchNextPage()}
            >
              {t("clients.loadMore")}
            </Button>
          )}
        </>
      )}
    </section>
  );
}
