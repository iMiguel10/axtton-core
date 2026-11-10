import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { DetailSkeleton } from "@/shared/components/Loading";
import { PdfButton } from "@/shared/components/PdfButton";
import { BackLink } from "@/shared/components/nav/BackLink";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { useDates } from "@/shared/lib/dates";
import { errorMessage } from "@/shared/lib/errors";
import { formatEur, formatPercentBp } from "@/shared/money";

import { ClientStatusBadge, ProgressDetails } from "./ClientProgress";
import { DecisionPanel } from "./DecisionPanel";
import { fetchOrder, fetchQuotePdf, makeAndModel, type PortalQuote, type QuoteLine } from "./api";

/** El detalle de una orden: diagnóstico, presupuesto y trabajos. Nunca las notas (RF-43). */
export function OrderDetailPage() {
  const { t } = useTranslation();
  const dates = useDates();
  const { orderId = "" } = useParams();
  const order = useQuery({
    queryKey: ["portal", "orders", orderId],
    queryFn: () => fetchOrder(orderId),
  });
  const back = <BackLink to="/">{t("portal.order.back")}</BackLink>;

  if (order.isPending) return <DetailSkeleton />;
  if (!order.data) {
    return (
      <>
        {back}
        <p role="alert">{errorMessage(t, order.error)}</p>
      </>
    );
  }

  const { code, progress, vehicle, diagnosis, quotes, work } = order.data;
  const [current, ...previous] = quotes;
  return (
    <>
      <div className="grid gap-3">
        {back}
        <div className="grid gap-1">
          <p className="text-muted-foreground text-sm">
            <span className="tabular-nums">{vehicle.plate}</span>
            {makeAndModel(vehicle) && ` · ${makeAndModel(vehicle)}`}
          </p>
          <h1 className="text-2xl font-semibold tabular-nums">{code}</h1>
        </div>
        <div>
          <ClientStatusBadge status={progress.status} />
        </div>
        <ProgressDetails progress={progress} />
      </div>

      <Section title={t("portal.order.diagnosis")}>
        {diagnosis ? (
          <p className="whitespace-pre-wrap">{diagnosis.text}</p>
        ) : (
          <p className="text-muted-foreground text-sm">{t("portal.order.noDiagnosis")}</p>
        )}
      </Section>

      <Section title={t("portal.order.quote")}>
        {current ? (
          <div className="grid gap-4">
            <QuoteVersion quote={current} />
            <DecisionPanel orderId={orderId} quote={current} />
            {previous.length > 0 && (
              <details className="border-t pt-3">
                <summary className="cursor-pointer text-sm font-medium">
                  {t("portal.order.previousVersions", { count: previous.length })}
                </summary>
                <div className="mt-3 grid gap-6">
                  {previous.map((quote) => (
                    <QuoteVersion key={quote.id} quote={quote} />
                  ))}
                </div>
              </details>
            )}
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">{t("portal.order.noQuote")}</p>
        )}
      </Section>

      <Section title={t("portal.order.work")}>
        {work.length > 0 ? (
          <ul className="grid gap-3">
            {work.map((entry, index) => (
              <li key={index} className="grid gap-0.5">
                <p className="whitespace-pre-wrap">{entry.description}</p>
                <p className="text-muted-foreground text-sm">{dates.day(entry.worked_on)}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">{t("portal.order.noWork")}</p>
        )}
      </Section>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function QuoteVersion({ quote }: { quote: PortalQuote }) {
  const { t } = useTranslation();
  const dates = useDates();
  // `valid_until` es la medianoche que cierra el último día: se enseña ese día.
  const lastValidDay = quote.valid_until
    ? dates.date(new Date(Date.parse(quote.valid_until) - 1).toISOString())
    : null;
  return (
    <div className="grid gap-3">
      <div className="grid gap-1">
        <p className="text-sm font-medium">
          {t("portal.order.version", { number: quote.version_no })} ·{" "}
          {t(`portal.order.quoteStatuses.${quote.status}`)}
        </p>
        <QuoteNotes quote={quote} lastValidDay={lastValidDay} />
      </div>
      <ul className="divide-y">
        {quote.lines.map((line, index) => (
          <Line key={index} line={line} />
        ))}
      </ul>
      <dl className="grid gap-1 border-t pt-3 text-sm">
        <Amount label={t("portal.order.subtotal")} cents={quote.subtotal_cents} />
        {quote.global_discount_cents > 0 && (
          <Amount label={t("portal.order.discount")} cents={-quote.global_discount_cents} />
        )}
        {quote.vat_breakdown.map((group) => (
          <Amount
            key={group.vat_bp}
            label={t("portal.order.vat", {
              rate: formatPercentBp(group.vat_bp),
              base: formatEur(group.base_cents),
            })}
            cents={group.vat_cents}
          />
        ))}
        <Amount label={t("portal.order.total")} cents={quote.total_cents} strong />
      </dl>
      <div className="flex flex-wrap gap-2">
        <PdfButton load={() => fetchQuotePdf(quote.id)} label={t("portal.order.pdf")} />
      </div>
    </div>
  );
}

function QuoteNotes({ quote, lastValidDay }: { quote: PortalQuote; lastValidDay: string | null }) {
  const { t } = useTranslation();
  const dates = useDates();
  const className = "text-muted-foreground text-sm";
  if (quote.decision) {
    return (
      <>
        <p className={className}>
          {t(`portal.order.decided.${quote.decision.outcome}`, {
            date: dates.date(quote.decision.decided_at),
            channel: t(`portal.order.channels.${quote.decision.channel}`),
          })}
        </p>
        {quote.delivery_on && (
          <p className={className}>
            {t("portal.progress.expected")}: {dates.day(quote.delivery_on)}
          </p>
        )}
      </>
    );
  }
  if (quote.status === "expired") {
    return <p className="text-status-pending-approval text-sm">{t("portal.order.expiredNote")}</p>;
  }
  if (quote.status !== "sent") return null;
  return (
    <>
      <p className={className}>{t("portal.order.validUntil", { date: lastValidDay })}</p>
      {quote.delivery_business_days && (
        <p className={className}>
          {t("portal.order.deliveryDays", { count: quote.delivery_business_days })}
        </p>
      )}
    </>
  );
}

function Line({ line }: { line: QuoteLine }) {
  const { t, i18n } = useTranslation();
  const quantity = Number(line.quantity).toLocaleString(i18n.language, { maximumFractionDigits: 3 });
  return (
    <li className="flex items-start justify-between gap-3 py-2">
      <div className="grid gap-0.5">
        <p>{line.description}</p>
        {line.part_condition && line.part_condition !== "new" && (
          <p className="text-status-pending-approval text-sm font-medium">
            {t(`portal.order.conditions.${line.part_condition}`)}
          </p>
        )}
        <p className="text-muted-foreground text-sm">
          {t(`portal.order.kinds.${line.kind}`)} · {quantity} × {formatEur(line.unit_price_cents)}
          {line.discount_bp > 0 && ` · ${t("portal.order.lineDiscount", { rate: formatPercentBp(line.discount_bp) })}`}
          {` · ${t("portal.order.lineVat", { rate: formatPercentBp(line.vat_bp) })}`}
        </p>
      </div>
      <span className="tabular-nums">{formatEur(line.amount_cents)}</span>
    </li>
  );
}

function Amount({ label, cents, strong }: { label: string; cents: number; strong?: boolean }) {
  return (
    <div className={`flex justify-between gap-3 ${strong ? "text-base font-semibold" : ""}`}>
      <dt className={strong ? undefined : "text-muted-foreground"}>{label}</dt>
      <dd className="tabular-nums">{formatEur(cents)}</dd>
    </div>
  );
}
