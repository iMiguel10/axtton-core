import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { SearchX, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/shared/components/EmptyState";
import { TableSkeleton } from "@/shared/components/Loading";
import { SearchInput, SwitchFilter } from "@/shared/components/filters/Filters";
import { Badge } from "@/shared/components/ui/badge";
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

import { clientName } from "./clientName";
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
      <div className="flex flex-wrap items-center justify-end gap-2">
        {canManageClients && (
          // Un enlace con aspecto de botón: lleva a otra pantalla, no hace nada aquí.
          <Link to="/clients/new" className={buttonVariants()}>
            {t("clients.new")}
          </Link>
        )}
      </div>
      <Card>
        <CardHeader className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <SearchInput
            aria-label={t("clients.search")}
            placeholder={t("clients.searchPlaceholder")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <SwitchFilter label={t("clients.showArchived")} checked={archived} onChange={setArchived} />
        </CardHeader>
        <CardContent>
      {clients.isPending ? (
        <TableSkeleton />
      ) : clients.isError ? (
        <p role="alert">{errorMessage(t, clients.error)}</p>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={filters.q ? SearchX : Users}
          title={t(filters.q ? "clients.noResults" : archived ? "clients.noArchived" : "clients.empty")}
          action={
            canManageClients && !filters.q && !archived && (
              <Link to="/clients/new" className={buttonVariants({ size: "sm" })}>
                {t("clients.new")}
              </Link>
            )
          }
        />
      ) : (
        <>
          <MobileCards>
            {rows.map((client) => (
              <MobileCard
                key={client.id}
                to={`/clients/${client.id}`}
                title={clientName(t, client.name)}
                aside={
                  client.kind === "company" && <Badge variant="outline">{t("clients.kinds.company")}</Badge>
                }
                lines={[client.phone, client.email]}
              />
            ))}
          </MobileCards>
          <div className="hidden md:block">
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
                <LinkRow key={client.id} to={`/clients/${client.id}`}>
                  <TableCell>
                    <Link to={`/clients/${client.id}`} className="link">
                      {clientName(t, client.name)}
                    </Link>
                    {client.kind === "company" && (
                      <Badge variant="outline" className="ml-2">
                        {t("clients.kinds.company")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>{client.phone}</TableCell>
                  <TableCell className="hidden md:table-cell">{client.email ?? "—"}</TableCell>
                </LinkRow>
              ))}
            </TableBody>
          </Table>
          </div>
          {clients.hasNextPage && (
            <Button
              variant="outline"
              className="mt-4"
              disabled={clients.isFetchingNextPage}
              onClick={() => void clients.fetchNextPage()}
            >
              {t("clients.loadMore")}
            </Button>
          )}
        </>
      )}
        </CardContent>
      </Card>
    </section>
  );
}
