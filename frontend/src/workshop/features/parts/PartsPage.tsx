import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Package, SearchX } from "lucide-react";
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
import { formatEur } from "@/shared/money";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { PAGE_SIZE, partsApi, type Part } from "./api";

/** El catálogo de piezas del taller activo (RF-90). Lo consulta todo el
 * personal; darlas de alta y fijar sus precios, solo el administrador. */
export function PartsPage() {
  const { t } = useTranslation();
  const { workshopId, canManageParts, canViewCosts } = useActiveWorkshop();
  const api = partsApi(workshopId);
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const filters = { q: useDebouncedValue(search), archived };

  // El taller va en la clave: al cambiar de taller nunca se enseña lo del anterior.
  const parts = useInfiniteQuery({
    queryKey: ["parts", workshopId, filters],
    queryFn: ({ pageParam }) => api.list(filters, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.parts.length < PAGE_SIZE ? undefined : pages.length * PAGE_SIZE,
    placeholderData: (previous) => previous,
  });
  const rows = parts.data?.pages.flatMap((page) => page.parts) ?? [];
  const pricesHidden = parts.data?.pages[0]?.prices_hidden ?? false;
  const price = (part: Part) =>
    part.sale_price_cents === null ? "—" : formatEur(part.sale_price_cents);

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {canManageParts && (
          <Link to="/parts/new" className={buttonVariants()}>
            {t("parts.new")}
          </Link>
        )}
      </div>
      <Card>
        <CardHeader className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <SearchInput
            aria-label={t("parts.search")}
            placeholder={t("parts.searchPlaceholder")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <SwitchFilter label={t("parts.showArchived")} checked={archived} onChange={setArchived} />
          {pricesHidden && (
            <p className="text-muted-foreground text-xs">{t("parts.pricesHidden")}</p>
          )}
        </CardHeader>
        <CardContent>
          {parts.isPending ? (
            <TableSkeleton />
          ) : parts.isError ? (
            <p role="alert">{errorMessage(t, parts.error)}</p>
          ) : rows.length === 0 ? (
            <EmptyState
              icon={filters.q ? SearchX : Package}
              title={t(filters.q ? "parts.noResults" : archived ? "parts.noArchived" : "parts.empty")}
              action={
                canManageParts &&
                !filters.q &&
                !archived && (
                  <Link to="/parts/new" className={buttonVariants({ size: "sm" })}>
                    {t("parts.new")}
                  </Link>
                )
              }
            />
          ) : (
            <>
              <MobileCards>
                {rows.map((part) => (
                  <MobileCard
                    key={part.id}
                    to={`/parts/${part.id}`}
                    title={part.description}
                    aside={<span className="text-sm tabular-nums">{price(part)}</span>}
                    lines={[[part.reference, part.brand].filter(Boolean).join(" · ")]}
                  />
                ))}
              </MobileCards>
              <div className="hidden md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("parts.reference")}</TableHead>
                      <TableHead>{t("parts.description")}</TableHead>
                      <TableHead>{t("parts.brandShort")}</TableHead>
                      {canViewCosts && (
                        <TableHead className="text-right">{t("parts.costPriceShort")}</TableHead>
                      )}
                      <TableHead className="text-right">{t("parts.salePriceShort")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((part) => (
                      <LinkRow key={part.id} to={`/parts/${part.id}`}>
                        <TableCell className="font-mono text-sm">{part.reference}</TableCell>
                        <TableCell>
                          <Link to={`/parts/${part.id}`} className="link">
                            {part.description}
                          </Link>
                          {part.part_condition !== "new" && (
                            <Badge variant="outline" className="ml-2">
                              {t(`parts.conditions.${part.part_condition}`)}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>{part.brand ?? "—"}</TableCell>
                        {canViewCosts && (
                          <TableCell className="text-right tabular-nums">
                            {part.cost_price_cents === null ? "—" : formatEur(part.cost_price_cents)}
                          </TableCell>
                        )}
                        <TableCell className="text-right tabular-nums">{price(part)}</TableCell>
                      </LinkRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {parts.hasNextPage && (
                <Button
                  variant="outline"
                  className="mt-4"
                  disabled={parts.isFetchingNextPage}
                  onClick={() => void parts.fetchNextPage()}
                >
                  {t("parts.loadMore")}
                </Button>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
