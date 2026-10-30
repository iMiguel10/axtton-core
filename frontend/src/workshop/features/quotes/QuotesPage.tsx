import { useInfiniteQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/shared/components/EmptyState";
import { TableSkeleton } from "@/shared/components/Loading";
import { When } from "@/shared/components/When";
import { SegmentedFilter } from "@/shared/components/filters/Filters";
import { LinkRow } from "@/shared/components/table/LinkRow";
import { MobileCard, MobileCards } from "@/shared/components/table/MobileCards";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader } from "@/shared/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/components/ui/table";
import { errorMessage } from "@/shared/lib/errors";
import { cn } from "@/shared/lib/utils";
import { formatEur } from "@/shared/money";

import { clientName } from "../clients/clientName";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { QUOTE_VIEWS, QUOTES_PAGE_SIZE, quotesApi, type QuoteListItem, type QuoteView } from "./api";

/**
 * Los presupuestos del taller activo, para llegar a ellos sin buscar la orden:
 * por defecto, los que esperan respuesta del cliente, los que caducan antes
 * primero. Cada fila lleva a la pestaña "Presupuesto" de su orden.
 */
export function QuotesPage() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [view, setView] = useState<QuoteView>("pending");
  const quotes = useInfiniteQuery({
    queryKey: ["quotes-list", workshopId, view],
    queryFn: ({ pageParam }) => quotesApi(workshopId).listAll(view, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.length < QUOTES_PAGE_SIZE ? undefined : pages.length * QUOTES_PAGE_SIZE,
    placeholderData: (previous) => previous,
  });
  const rows = quotes.data?.pages.flat() ?? [];

  return (
    <section className="grid gap-4">
      <Card>
        <CardHeader>
          <SegmentedFilter
            label={t("quotes.list.view")}
            value={view}
            options={QUOTE_VIEWS.map((value) => ({ value, label: t(`quotes.list.views.${value}`) }))}
            onChange={setView}
          />
        </CardHeader>
        <CardContent>
          {/* Al cambiar de filtro se ven los datos del anterior mientras llegan
              los nuevos; si estaban vacíos, "no hay" sería mentira: se espera. */}
          {quotes.isPending || (quotes.isPlaceholderData && rows.length === 0) ? (
            <TableSkeleton />
          ) : quotes.isError ? (
            <p role="alert">{errorMessage(t, quotes.error)}</p>
          ) : rows.length === 0 ? (
            <EmptyState
              icon={FileText}
              title={t(`quotes.list.none.${view}`)}
              description={t("quotes.list.noneHint")}
            />
          ) : (
            <div className={cn(quotes.isPlaceholderData && "opacity-60")}>
              <QuotesTable quotes={rows} />
              {quotes.hasNextPage && (
                <Button
                  variant="outline"
                  className="mt-4"
                  disabled={quotes.isFetchingNextPage}
                  onClick={() => void quotes.fetchNextPage()}
                >
                  {t("quotes.list.loadMore")}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

/** El enlace a la pestaña del presupuesto en la ficha de su orden. */
const linkTo = (quote: QuoteListItem) => `/orders/${quote.order_id}?tab=quotes`;

function QuoteStatusBadge({ quote }: { quote: QuoteListItem }) {
  const { t } = useTranslation();
  // Una enviada fuera de plazo se enseña caducada aunque su estado aún diga
  // "enviada": nadie la marca hasta el worker (F5).
  if (quote.expired) return <Badge variant="destructive">{t("quotes.statuses.expired")}</Badge>;
  return (
    <Badge variant={quote.status === "draft" ? "outline" : "secondary"}>
      {t(`quotes.statuses.${quote.status}`)}
    </Badge>
  );
}

function Deadline({ quote }: { quote: QuoteListItem }) {
  const { t } = useTranslation();
  if (quote.valid_until && quote.status === "sent") {
    return (
      <>
        {t("quotes.list.validUntil")} <When iso={quote.valid_until} />
      </>
    );
  }
  return (
    <>
      {t("quotes.list.updated")} <When iso={quote.updated_at} />
    </>
  );
}

function QuotesTable({ quotes }: { quotes: QuoteListItem[] }) {
  const { t } = useTranslation();
  const total = (quote: QuoteListItem) => (quote.total_cents === null ? "—" : formatEur(quote.total_cents));
  return (
    <>
      <MobileCards>
        {quotes.map((quote) => (
          <MobileCard
            key={quote.id}
            to={linkTo(quote)}
            title={`${quote.order_code} · ${t("quotes.version", { number: quote.version_no })}`}
            aside={<QuoteStatusBadge quote={quote} />}
            lines={[
              <>
                <span className="text-foreground tabular-nums">{quote.plate}</span>
                {` · ${clientName(t, quote.client_name)}`}
              </>,
              <span className="tabular-nums">{total(quote)}</span>,
              <Deadline quote={quote} />,
            ]}
          />
        ))}
      </MobileCards>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("orders.code")}</TableHead>
              <TableHead>{t("quotes.list.version")}</TableHead>
              <TableHead>{t("orders.status")}</TableHead>
              <TableHead>{t("orders.vehicle")}</TableHead>
              <TableHead>{t("orders.client")}</TableHead>
              <TableHead className="text-right">{t("quotes.total")}</TableHead>
              <TableHead className="hidden lg:table-cell">{t("quotes.list.when")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {quotes.map((quote) => (
              <LinkRow key={quote.id} to={linkTo(quote)}>
                <TableCell>
                  <Link to={linkTo(quote)} className="link tabular-nums">
                    {quote.order_code}
                  </Link>
                </TableCell>
                <TableCell className="tabular-nums">{quote.version_no}</TableCell>
                <TableCell>
                  <QuoteStatusBadge quote={quote} />
                </TableCell>
                <TableCell className="tabular-nums">{quote.plate}</TableCell>
                <TableCell>{clientName(t, quote.client_name)}</TableCell>
                <TableCell className="text-right tabular-nums">{total(quote)}</TableCell>
                <TableCell className="text-muted-foreground hidden text-sm lg:table-cell">
                  <Deadline quote={quote} />
                </TableCell>
              </LinkRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
