import { useInfiniteQuery } from "@tanstack/react-query";
import i18n, { type TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { TableSkeleton } from "@/shared/components/Loading";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent } from "@/shared/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/components/ui/table";
import { errorMessage } from "@/shared/lib/errors";
import { formatEur, formatPercentBp } from "@/shared/money";

import { clientName } from "../clients/clientName";
import { fetchAuditPage, type AuditEntry, type AuditScope } from "./api";

/** Registro de auditoría (RNF-16), del taller activo o de la plataforma. */
export function AuditPage({ scope }: { scope: AuditScope }) {
  const { t, i18n } = useTranslation();
  const audit = useInfiniteQuery({
    queryKey: ["audit", scope],
    queryFn: ({ pageParam }) => fetchAuditPage(scope, pageParam),
    initialPageParam: null as number | null,
    // Paginado por seq: la página siguiente son las entradas anteriores a la última.
    getNextPageParam: (last) => last.next_before,
  });
  const format = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "short",
    timeStyle: "short",
  });

  return (
    <section className="grid gap-6">
      {audit.isPending ? (
        <TableSkeleton />
      ) : audit.isError ? (
        <p role="alert">{errorMessage(t, audit.error)}</p>
      ) : (
        <>
          <Card>
            <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("audit.when")}</TableHead>
                <TableHead>{t("audit.who")}</TableHead>
                <TableHead>{t("audit.what")}</TableHead>
                <TableHead>{t("audit.on")}</TableHead>
                <TableHead>{t("audit.changes")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {audit.data.pages
                .flatMap((page) => page.entries)
                .map((entry) => (
                  <TableRow key={entry.seq}>
                    <TableCell className="whitespace-nowrap">
                      {format.format(new Date(entry.created_at))}
                    </TableCell>
                    <TableCell>{entry.actor ?? "—"}</TableCell>
                    <TableCell>
                      {t(`audit.actions.${entry.action}`, { defaultValue: entry.action })}
                    </TableCell>
                    <TableCell>
                      {entry.target_type === "client"
                        ? clientName(t, entry.target_name)
                        : (entry.target_name ?? "—")}
                    </TableCell>
                    <TableCell>
                      <Details entry={entry} t={t} />
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
          {audit.hasNextPage && (
            <Button
              variant="outline"
              className="mt-4"
              disabled={audit.isFetchingNextPage}
              onClick={() => void audit.fetchNextPage()}
            >
              {t("audit.loadMore")}
            </Button>
          )}
          </CardContent>
          </Card>
        </>
      )}
    </section>
  );
}

function Details({ entry, t }: { entry: AuditEntry; t: TFunction }) {
  const items = Object.entries(entry.details);
  if (items.length === 0) return <>—</>;
  return (
    <ul className="grid gap-0.5 text-sm">
      {items.map(([field, value]) => (
        <li key={field}>
          <span className="text-muted-foreground">
            {t(`audit.fields.${field}`, { defaultValue: field })}:
          </span>{" "}
          {Array.isArray(value) && value.length === 2
            ? `${show(t, field, value[0])} → ${show(t, field, value[1])}`
            : show(t, field, value)}
        </li>
      ))}
    </ul>
  );
}

/** Un valor guardado, como lo leería una persona. */
function show(t: TFunction, field: string, value: unknown): string {
  // Un cliente anonimizado (RF-15) llega con el nombre vacío.
  if (field === "client_id" && value === "") return clientName(t, "");
  if (value === null || value === undefined || value === "") return "—";
  if (field === "role") return t(`roles.${String(value)}`);
  if (field === "status") return t(`admin.statuses.${String(value)}`);
  if (field === "work_order_status") return t(`orders.statuses.${String(value)}`);
  if (field === "no_quote_reason") return t(`orders.noQuoteReasons.${String(value)}`);
  if (field === "hourly_cost_cents" && typeof value === "number") return formatEur(value);
  if (field === "paid_amount_cents" && typeof value === "number") return formatEur(value);
  if (field === "total_cents" && typeof value === "number") return formatEur(value);
  if (field === "hourly_price_cents" && typeof value === "number") return formatEur(value);
  if (field === "default_vat_bp" && typeof value === "number") return formatPercentBp(value);
  if (field === "payment_status") return t(`payment.statuses.${String(value)}`);
  if (field === "payment_method") return t(`payment.methods.${String(value)}`);
  if (field === "paid_on") return new Intl.DateTimeFormat(i18n.language, { timeZone: "UTC", dateStyle: "medium" }).format(new Date(`${String(value)}T00:00:00Z`));
  if (typeof value === "boolean") return t(value ? "common.yes" : "common.no");
  return String(value);
}
