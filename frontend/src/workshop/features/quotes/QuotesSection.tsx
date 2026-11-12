import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, FileText, Plus, RefreshCw, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmButton } from "@/shared/components/ConfirmButton";
import { EmptyState } from "@/shared/components/EmptyState";
import { LinesSkeleton } from "@/shared/components/Loading";
import { notify } from "@/shared/components/Toaster";
import { Select } from "@/shared/components/form/Select";
import { Textarea } from "@/shared/components/form/Textarea";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Input } from "@/shared/components/ui/input";
import { Label } from "@/shared/components/ui/label";
import { ApiError } from "@/shared/lib/apiClient";
import { useDates } from "@/shared/lib/dates";
import { errorMessage } from "@/shared/lib/errors";
import {
  bpToInput,
  centsToInput,
  formatEur,
  formatPercentBp,
  parseEurToCents,
  parsePercentToBp,
} from "@/shared/money";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { settingsApi } from "../settings/api";
import { PdfButton } from "./PdfButton";
import {
  awaitsAnswer,
  LINE_KINDS,
  PART_CONDITIONS,
  quotesApi,
  type DecisionOutcome,
  type DiscountKind,
  type DraftInput,
  type LineKind,
  type PartCondition,
  type Quote,
  type QuoteDecision,
  type QuoteTotals,
} from "./api";

/**
 * Los presupuestos de una orden (RF-30 a RF-32): las versiones, de la más nueva
 * a la más antigua, y el borrador editable para quien los prepara. Los importes
 * los calcula siempre la API: el navegador solo los pinta (RNF-14).
 */
export function QuotesSection({
  orderId,
  closed,
  onOrderChanged,
}: {
  orderId: string;
  closed: boolean;
  /** Enviar o anular cambian el estado de la orden: la ficha se recarga. */
  onOrderChanged: () => unknown;
}) {
  const { t } = useTranslation();
  const { workshopId, canManageQuotes } = useActiveWorkshop();
  const api = quotesApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["quotes", workshopId, orderId];
  const quotes = useQuery({ queryKey, queryFn: () => api.list(orderId) });
  const create = useMutation({
    mutationFn: () => api.create(orderId),
    // El listado de la barra lateral también cambia.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey }),
        queryClient.invalidateQueries({ queryKey: ["quotes-list", workshopId] }),
      ]),
  });

  if (!quotes.data) {
    return quotes.isError ? <p role="alert">{errorMessage(t, quotes.error)}</p> : <LinesSkeleton lines={4} />;
  }
  const versions = quotes.data;
  const draft = versions.find((quote) => quote.status === "draft");
  const canCreate = canManageQuotes && !closed && !draft;

  return (
    <div className="grid gap-4">
      {canCreate && (
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={create.isPending} onClick={() => create.mutate()}>
            <Plus aria-hidden />
            {t(versions.length ? "quotes.newVersion" : "quotes.new")}
          </Button>
          {versions.length > 0 && (
            <span className="text-muted-foreground text-sm">{t("quotes.newVersionHint")}</span>
          )}
        </div>
      )}
      {create.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, create.error)}
        </p>
      )}
      {versions.length === 0 ? (
        <EmptyState icon={FileText} title={t("quotes.none")} description={t("quotes.noneHint")} />
      ) : (
        versions.map((quote) =>
          quote.status === "draft" && canManageQuotes && !closed ? (
            // Por id, no por versión: guardar sube la versión y remontar el
            // editor borraría lo que se está escribiendo (RNF-15).
            <DraftEditor key={quote.id} quote={quote} queryKey={queryKey} onOrderChanged={onOrderChanged} />
          ) : (
            <QuoteCard
              key={quote.id}
              quote={quote}
              // Anular es del administrador, con la orden abierta, y de una
              // versión que espera respuesta (también si ya pasó su plazo, la
              // haya marcado o no el worker).
              canCancel={canManageQuotes && !closed && awaitsAnswer(quote)}
              // Renovar crea una versión nueva: no con una corrección a medias.
              canRenew={canManageQuotes && !closed && awaitsAnswer(quote) && !draft}
              // Registrar la respuesta del cliente: enviada y en plazo (RF-33).
              canDecide={canManageQuotes && !closed && quote.status === "sent" && !quote.expired}
              queryKey={queryKey}
              onOrderChanged={onOrderChanged}
            />
          ),
        )
      )}
    </div>
  );
}

/**
 * El último día en que vale: `valid_until` es la medianoche que lo cierra (el
 * instante en que deja de valer), así que se enseña el día anterior a ese
 * instante, en la zona del taller.
 */
function lastValidDay(dates: ReturnType<typeof useDates>, validUntil: string | null): string | null {
  if (!validUntil) return null;
  return dates.date(new Date(Date.parse(validUntil) - 1).toISOString());
}

function QuoteHeader({ quote }: { quote: Quote }) {
  const { t } = useTranslation();
  const dates = useDates();
  return (
    <CardHeader>
      <CardTitle className="flex flex-wrap items-center gap-2">
        {t("quotes.version", { number: quote.version_no })}
        {/* Fuera de plazo se enseña caducada aunque su estado aún diga
            "enviada": el worker la marca cada hora (F5). */}
        {quote.expired ? (
          <Badge variant="destructive">{t("quotes.statuses.expired")}</Badge>
        ) : (
          <Badge variant={quote.status === "draft" ? "outline" : "secondary"}>
            {t(`quotes.statuses.${quote.status}`)}
          </Badge>
        )}
      </CardTitle>
      <CardDescription>
        {quote.sent_at
          ? t("quotes.sentOn", {
              sent: dates.dateTime(quote.sent_at),
              until: lastValidDay(dates, quote.valid_until),
            })
          : t("quotes.draftHint")}
      </CardDescription>
    </CardHeader>
  );
}

/** Una versión que ya no se edita: lo que se envió, tal como se guardó. */
function QuoteCard({
  quote,
  canCancel,
  canRenew,
  canDecide,
  queryKey,
  onOrderChanged,
}: {
  quote: Quote;
  canCancel: boolean;
  canRenew: boolean;
  canDecide: boolean;
  queryKey: unknown[];
  onOrderChanged: () => unknown;
}) {
  const { t } = useTranslation();
  const dates = useDates();
  const { workshopId } = useActiveWorkshop();
  const queryClient = useQueryClient();
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  // La validez del taller, para decir cuánto valdrá la renovada.
  const settings = useQuery({
    queryKey: ["settings", workshopId],
    queryFn: settingsApi(workshopId).get,
    enabled: canRenew,
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ["quotes-list", workshopId] }),
      onOrderChanged(),
    ]);
  const cancel = useMutation({
    mutationFn: () => quotesApi(workshopId).cancel(quote.id, quote.version, reason.trim()),
    onSuccess: () => {
      setCancelling(false);
      setReason("");
      notify(t("quotes.cancelled"));
    },
    onSettled: refresh,
  });
  // Ampliar el plazo sin tocar lo enviado: una copia, enviada con validez nueva.
  const renew = useMutation({
    mutationFn: () => quotesApi(workshopId).renew(quote.id, quote.version),
    onSuccess: () => notify(t("quotes.renewed")),
    onSettled: refresh,
  });
  return (
    <Card>
      <QuoteHeader quote={quote} />
      {quote.status === "sent" && !quote.expired && (
        <p className="text-muted-foreground -mt-2 px-6 text-sm">{t("quotes.waitingHint")}</p>
      )}
      {quote.expired && (
        <p className="text-destructive -mt-2 px-6 text-sm">{t("quotes.expiredHint")}</p>
      )}
      {quote.status === "cancelled" && quote.cancel_reason && (
        <p className="text-muted-foreground -mt-2 px-6 text-sm">
          {t("quotes.cancelledBecause", { reason: quote.cancel_reason })}
        </p>
      )}
      {quote.decision && <DecisionSummary decision={quote.decision} />}
      <CardContent className="grid gap-4">
        {canDecide && <DecisionForm quote={quote} onDecided={refresh} />}
        {quote.prices_hidden && (
          <p className="text-muted-foreground text-sm">{t("quotes.pricesHidden")}</p>
        )}
        {quote.lines.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("quotes.noLines")}</p>
        ) : (
          <ul className="divide-y">
            {quote.lines.map((line) => (
              <li key={line.id} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                <div className="grid">
                  <span>
                    {line.description}
                    {line.part_condition && line.part_condition !== "new" && (
                      <Badge variant="outline" className="ml-2">
                        {t(`quotes.conditions.${line.part_condition}`)}
                      </Badge>
                    )}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {t(`quotes.kinds.${line.kind}`)}
                    {line.reference && ` · ${line.reference}`}
                    {` · ${formatQuantity(line.quantity)}`}
                    {line.unit_price_cents !== null && ` × ${formatEur(line.unit_price_cents)}`}
                    {line.discount_bp > 0 && ` · −${formatPercentBp(line.discount_bp)}`}
                  </span>
                </div>
                {line.taxable_cents !== null && (
                  <span className="tabular-nums">{formatEur(line.taxable_cents)}</span>
                )}
              </li>
            ))}
          </ul>
        )}
        {quote.totals && <Totals totals={quote.totals} />}
        {quote.delivery_business_days !== null && (
          <p className="text-muted-foreground text-sm">
            {t("quotes.deliveryTerm", { count: quote.delivery_business_days })}
            {quote.delivery_on && (
              <>
                {" · "}
                <span className="text-foreground font-medium">
                  {t("quotes.deliveryOn", { date: dates.day(quote.delivery_on) })}
                </span>
              </>
            )}
          </p>
        )}
        {canCancel && cancelling ? (
          // Anular exige un motivo (§6), como cancelar una orden.
          <form
            className="grid gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              cancel.mutate();
            }}
          >
            <Label htmlFor={`cancel-${quote.id}`}>{t("quotes.cancelReason")}</Label>
            <Textarea
              id={`cancel-${quote.id}`}
              autoFocus
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              <Button type="submit" variant="destructive" size="sm" disabled={!reason.trim() || cancel.isPending}>
                {t("quotes.cancel")}
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setCancelling(false)}>
                {t("common.cancel")}
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap gap-2">
            {/* Sin importes no hay presupuesto que descargar (§3). */}
            {!quote.prices_hidden && <PdfButton quoteId={quote.id} label={t("quotes.pdf")} />}
            {canRenew && (
              <ConfirmButton
                variant={quote.expired ? "default" : "outline"}
                size="sm"
                disabled={renew.isPending}
                title={t("quotes.renewTitle", { number: quote.version_no })}
                description={t("quotes.confirmRenew", {
                  days: settings.data?.quote_validity_business_days ?? 12,
                })}
                confirmLabel={t("quotes.renew")}
                onConfirm={() => renew.mutate()}
              >
                <RefreshCw aria-hidden />
                {t("quotes.renew")}
              </ConfirmButton>
            )}
            {canCancel && (
              <Button variant="outline" size="sm" onClick={() => setCancelling(true)}>
                {t("quotes.cancel")}
              </Button>
            )}
          </div>
        )}
        {(cancel.isError || renew.isError) && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, cancel.error ?? renew.error)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** Quién decidió, cuándo y por dónde (RF-36). */
function DecisionSummary({ decision }: { decision: QuoteDecision }) {
  const { t } = useTranslation();
  const dates = useDates();
  return (
    <div className="-mt-2 grid gap-1 px-6 text-sm">
      <p className={decision.outcome === "approved" ? "text-foreground" : "text-muted-foreground"}>
        {t(`quotes.decision.summary.${decision.outcome}`, {
          channel: t(`quotes.decision.channels.${decision.channel}`),
          when: dates.dateTime(decision.decided_at),
        })}
        {decision.recorded_by_name && ` · ${t("quotes.decision.recordedBy", { name: decision.recorded_by_name })}`}
      </p>
      {decision.note && <p className="text-muted-foreground whitespace-pre-line">{decision.note}</p>}
      {(decision.ip || decision.user_agent) && (
        <p className="text-muted-foreground text-xs break-all">
          {t("quotes.decision.evidence", { ip: decision.ip ?? "—", browser: decision.user_agent ?? "—" })}
        </p>
      )}
    </div>
  );
}

/**
 * La respuesta que el cliente dio por teléfono o en persona (RF-35). Como prueba
 * vale menos que la del portal o una firmada, y el formulario lo dice.
 */
function DecisionForm({ quote, onDecided }: { quote: Quote; onDecided: () => unknown }) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState<DecisionOutcome>("approved");
  const [channel, setChannel] = useState<"phone" | "in_person">("phone");
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: () =>
      quotesApi(workshopId).decide(quote.id, quote.version, {
        outcome,
        channel,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      setOpen(false);
      notify(t(`quotes.decision.done.${outcome}`));
    },
    onSettled: onDecided,
  });

  if (!open) {
    return (
      <Button className="justify-self-start" onClick={() => setOpen(true)}>
        <CheckCircle aria-hidden />
        {t("quotes.decision.record")}
      </Button>
    );
  }
  const id = (field: string) => `${quote.id}-decision-${field}`;
  return (
    <form
      className="grid gap-3 rounded-lg border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        decide.mutate();
      }}
    >
      <p className="font-medium">{t("quotes.decision.title")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1">
          <Label htmlFor={id("outcome")}>{t("quotes.decision.outcome")}</Label>
          <Select id={id("outcome")} value={outcome} onChange={(e) => setOutcome(e.target.value as DecisionOutcome)}>
            <option value="approved">{t("quotes.decision.outcomes.approved")}</option>
            <option value="rejected">{t("quotes.decision.outcomes.rejected")}</option>
          </Select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor={id("channel")}>{t("quotes.decision.channel")}</Label>
          <Select
            id={id("channel")}
            value={channel}
            onChange={(e) => setChannel(e.target.value as "phone" | "in_person")}
          >
            <option value="phone">{t("quotes.decision.channels.phone")}</option>
            <option value="in_person">{t("quotes.decision.channels.in_person")}</option>
          </Select>
        </div>
      </div>
      <div className="grid gap-1">
        <Label htmlFor={id("note")}>{t("quotes.decision.note")}</Label>
        <Textarea id={id("note")} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <p className="text-muted-foreground text-xs">{t("quotes.decision.weakProof")}</p>
      {decide.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, decide.error)}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant={outcome === "rejected" ? "destructive" : "default"} disabled={decide.isPending}>
          {t(`quotes.decision.submit.${outcome}`)}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
          {t("common.cancel")}
        </Button>
      </div>
    </form>
  );
}

function Totals({ totals }: { totals: QuoteTotals }) {
  const { t } = useTranslation();
  const rows: [string, number][] = [[t("quotes.subtotal"), totals.subtotal_cents]];
  // El descuento global sale como tal, no repartido (RF-39).
  if (totals.global_discount_cents > 0) rows.push([t("quotes.globalDiscount"), -totals.global_discount_cents]);
  for (const group of totals.vat_breakdown) {
    const rate = formatPercentBp(group.vat_bp);
    rows.push([t("quotes.base", { rate }), group.base_cents]);
    rows.push([t("quotes.vat", { rate }), group.vat_cents]);
  }
  return (
    <dl className="ml-auto grid w-full max-w-xs grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
      {rows.map(([label, cents]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="text-right tabular-nums">{formatEur(cents)}</dd>
        </div>
      ))}
      <dt className="border-t pt-1 font-medium">{t("quotes.total")}</dt>
      <dd className="border-t pt-1 text-right font-medium tabular-nums">{formatEur(totals.total_cents)}</dd>
    </dl>
  );
}

// --- El borrador ---------------------------------------------------------------

/** Una línea tal como se escribe: texto, para no perder lo tecleado a medias. */
type LineDraft = {
  key: string;
  kind: LineKind;
  description: string;
  reference: string;
  condition: PartCondition;
  quantity: string;
  price: string;
  discount: string;
  vat: string;
};

let nextKey = 0;
const newKey = () => `line-${nextKey++}`;

/** "1.500" → "1,5": la cantidad como se escribiría. */
function formatQuantity(value: string): string {
  return String(Number(value)).replace(".", ",");
}

/** "1,5" → "1.5"; nulo si no es una cantidad positiva con tres decimales como mucho. */
function parseQuantity(value: string): string | null {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d{1,7}(\.\d{1,3})?$/.test(normalized) || Number(normalized) <= 0) return null;
  return normalized;
}

function toDraftLines(quote: Quote): LineDraft[] {
  return quote.lines.map((line) => ({
    key: newKey(),
    kind: line.kind,
    description: line.description,
    reference: line.reference ?? "",
    condition: line.part_condition ?? "new",
    quantity: formatQuantity(line.quantity),
    price: line.unit_price_cents === null ? "" : centsToInput(line.unit_price_cents),
    discount: bpToInput(line.discount_bp),
    vat: bpToInput(line.vat_bp),
  }));
}

type Discount = { kind: DiscountKind | "none"; value: string };

function toDiscount(quote: Quote): Discount {
  if (quote.global_discount_kind === null || quote.global_discount_value === null) {
    return { kind: "none", value: "" };
  }
  return {
    kind: quote.global_discount_kind,
    value:
      quote.global_discount_kind === "percent"
        ? bpToInput(quote.global_discount_value)
        : centsToInput(quote.global_discount_value),
  };
}

/** "5" → 5; vacío → null (puede faltar hasta enviarlo); undefined si no vale. */
function parseDelivery(value: string): number | null | undefined {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  if (!/^\d{1,3}$/.test(trimmed)) return undefined;
  const days = Number(trimmed);
  return days >= 1 && days <= 250 ? days : undefined;
}

/** Lo escrito, pasado a lo que espera la API; o la lista de líneas con errores. */
function toInput(
  lines: LineDraft[],
  discount: Discount,
  delivery: string,
): DraftInput | { invalid: Set<string> } {
  const invalid = new Set<string>();
  const parsed = lines.map((line) => {
    const quantity = parseQuantity(line.quantity);
    const price = parseEurToCents(line.price);
    const lineDiscount = line.discount.trim() === "" ? 0 : parsePercentToBp(line.discount);
    const vat = parsePercentToBp(line.vat);
    if (!line.description.trim() || quantity === null || price === null || lineDiscount === null || vat === null) {
      invalid.add(line.key);
    }
    return {
      kind: line.kind,
      description: line.description.trim(),
      reference: line.kind === "part" ? line.reference.trim() || null : null,
      part_condition: line.kind === "part" ? line.condition : null,
      quantity: quantity ?? "0",
      unit_price_cents: price ?? 0,
      discount_bp: lineDiscount ?? 0,
      vat_bp: vat ?? 0,
    };
  });
  let globalDiscount: DraftInput["global_discount"] = null;
  if (discount.kind !== "none" && discount.value.trim() !== "") {
    const value = discount.kind === "percent" ? parsePercentToBp(discount.value) : parseEurToCents(discount.value);
    if (value === null) invalid.add("discount");
    else globalDiscount = { kind: discount.kind, value };
  }
  const deliveryDays = parseDelivery(delivery);
  if (deliveryDays === undefined) invalid.add("delivery");
  return invalid.size
    ? { invalid }
    : { lines: parsed, global_discount: globalDiscount, delivery_business_days: deliveryDays ?? null };
}

function DraftEditor({
  quote,
  queryKey,
  onOrderChanged,
}: {
  quote: Quote;
  queryKey: unknown[];
  onOrderChanged: () => unknown;
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = quotesApi(workshopId);
  const settings = settingsApi(workshopId);
  const queryClient = useQueryClient();
  // Para proponer la tarifa y el IVA del taller en una línea nueva.
  const workshop = useQuery({ queryKey: ["settings", workshopId], queryFn: settings.get });
  const rates = useQuery({ queryKey: ["labor-rates", workshopId, false], queryFn: () => settings.rates(false) });

  const [lines, setLines] = useState<LineDraft[]>(() => toDraftLines(quote));
  const [discount, setDiscount] = useState<Discount>(() => toDiscount(quote));
  const [delivery, setDelivery] = useState(() => quote.delivery_business_days?.toString() ?? "");
  // La versión desde la que se edita: guardar la sube, y un 409 avisa de que
  // otra persona guardó antes (RNF-15).
  const [baseVersion, setBaseVersion] = useState(quote.version);
  const [dirty, setDirty] = useState(false);
  const [invalid, setInvalid] = useState<Set<string>>(new Set());

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ["quotes-list", workshopId] }),
    ]);
  const save = useMutation({
    mutationFn: ({ input, version }: { input: DraftInput; version: number }) =>
      api.save(quote.id, version, input),
    onSuccess: ({ version }) => {
      setBaseVersion(version);
      setDirty(false);
      notify(t("quotes.saved"));
    },
    onSettled: refresh,
  });
  const discard = useMutation({
    mutationFn: () => api.discard(quote.id, baseVersion),
    onSuccess: () => notify(t("quotes.discarded")),
    onSettled: refresh,
  });
  // Enviar congela lo guardado: con cambios sin guardar no se ofrece, para que
  // no se envíe algo distinto de lo que se ve.
  const send = useMutation({
    mutationFn: () => api.send(quote.id, baseVersion),
    onSuccess: () => notify(t("quotes.sent")),
    onSettled: () => Promise.all([refresh(), onOrderChanged()]),
  });
  // Otra persona guardó el borrador mientras se editaba: lo escrito sigue aquí
  // (no se remonta el editor) y se elige qué hacer, como con el diagnóstico.
  const conflict = save.error instanceof ApiError && save.error.code === "modified_by_someone_else";

  const change = (key: string, patch: Partial<LineDraft>) => {
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));
    setDirty(true);
  };
  const add = (kind: LineKind) => {
    const vat = bpToInput(workshop.data?.default_vat_bp ?? 2100);
    const rate = rates.data?.find((r) => r.is_default);
    setLines((current) => [
      ...current,
      {
        key: newKey(),
        kind,
        // La mano de obra copia la tarifa por defecto (RF-38): se puede cambiar.
        description: kind === "labor" && rate ? rate.name : "",
        reference: "",
        condition: "new",
        quantity: "1",
        price: kind === "labor" && rate ? centsToInput(rate.hourly_price_cents) : "",
        discount: "0",
        vat,
      },
    ]);
    setDirty(true);
  };
  const remove = (key: string) => {
    setLines((current) => current.filter((line) => line.key !== key));
    setDirty(true);
  };
  // `version`: la desde la que se editó o, para guardar lo mío encima de lo del
  // otro, la última que hay (la recarga tras el 409 ya la trajo).
  const submit = (version = baseVersion) => {
    const input = toInput(lines, discount, delivery);
    if ("invalid" in input) {
      setInvalid(input.invalid);
      return;
    }
    setInvalid(new Set());
    save.mutate({ input, version });
  };
  const reload = () => {
    setLines(toDraftLines(quote));
    setDiscount(toDiscount(quote));
    setDelivery(quote.delivery_business_days?.toString() ?? "");
    setBaseVersion(quote.version);
    setDirty(false);
    save.reset();
  };

  return (
    <Card>
      <QuoteHeader quote={quote} />
      <CardContent className="grid gap-4">
        {lines.length === 0 && <p className="text-muted-foreground text-sm">{t("quotes.noLines")}</p>}
        <ol className="grid gap-3">
          {lines.map((line, index) => (
            <LineEditor
              key={line.key}
              line={line}
              number={index + 1}
              invalid={invalid.has(line.key)}
              rates={rates.data ?? []}
              onChange={(patch) => change(line.key, patch)}
              onRemove={() => remove(line.key)}
            />
          ))}
        </ol>
        <div className="flex flex-wrap gap-2">
          {LINE_KINDS.map((kind) => (
            <Button key={kind} variant="outline" size="sm" onClick={() => add(kind)}>
              <Plus aria-hidden />
              {t(`quotes.add.${kind}`)}
            </Button>
          ))}
        </div>

        <div className="grid gap-1.5 sm:max-w-md">
          <Label htmlFor={`discount-${quote.id}`}>{t("quotes.globalDiscount")}</Label>
          <div className="flex gap-2">
            <Select
              aria-label={t("quotes.discountKind")}
              value={discount.kind}
              onChange={(event) => {
                setDiscount({ kind: event.target.value as Discount["kind"], value: "" });
                setDirty(true);
              }}
            >
              <option value="none">{t("quotes.discountKinds.none")}</option>
              <option value="percent">{t("quotes.discountKinds.percent")}</option>
              <option value="amount">{t("quotes.discountKinds.amount")}</option>
            </Select>
            {discount.kind !== "none" && (
              <Input
                id={`discount-${quote.id}`}
                inputMode="decimal"
                value={discount.value}
                aria-invalid={invalid.has("discount") || undefined}
                onChange={(event) => {
                  setDiscount({ ...discount, value: event.target.value });
                  setDirty(true);
                }}
              />
            )}
          </div>
        </div>

        <div className="grid gap-1.5 sm:max-w-md">
          <Label htmlFor={`delivery-${quote.id}`}>{t("quotes.delivery")}</Label>
          <Input
            id={`delivery-${quote.id}`}
            inputMode="numeric"
            className="sm:max-w-32"
            value={delivery}
            aria-invalid={invalid.has("delivery") || undefined}
            aria-describedby={`delivery-${quote.id}-hint`}
            onChange={(event) => {
              setDelivery(event.target.value);
              setDirty(true);
            }}
          />
          <p id={`delivery-${quote.id}-hint`} className="text-muted-foreground text-xs">
            {t("quotes.deliveryHint")}
          </p>
        </div>

        {invalid.has("delivery") && (
          <p role="alert" className="text-destructive text-sm">
            {t("quotes.invalidDelivery")}
          </p>
        )}
        {[...invalid].some((key) => key !== "delivery") && (
          <p role="alert" className="text-destructive text-sm">
            {t("quotes.fixLines")}
          </p>
        )}
        {conflict ? (
          <div role="alert" className="grid gap-2 rounded-lg border border-destructive/40 p-3 text-sm">
            <p className="text-destructive">{t("quotes.conflict")}</p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={reload}>
                {t("quotes.reload")}
              </Button>
              <Button variant="outline" size="sm" onClick={() => submit(quote.version)}>
                {t("quotes.overwrite")}
              </Button>
            </div>
          </div>
        ) : (
          (save.isError || discard.isError || send.isError) && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(t, save.error ?? discard.error ?? send.error)}
            </p>
          )
        )}

        {quote.totals && (
          <div className="grid gap-1">
            <Totals totals={quote.totals} />
            {dirty && (
              <p className="text-muted-foreground text-right text-xs">{t("quotes.totalsAfterSave")}</p>
            )}
          </div>
        )}

        {!dirty && quote.delivery_business_days === null && lines.length > 0 && (
          <p className="text-muted-foreground text-sm">{t("quotes.deliveryMissing")}</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={save.isPending || !dirty} onClick={() => submit()}>
            {t("common.save")}
          </Button>
          <ConfirmButton
            disabled={dirty || lines.length === 0 || quote.delivery_business_days === null || send.isPending}
            title={t("quotes.sendTitle", { number: quote.version_no })}
            description={t("quotes.confirmSend", {
              days: workshop.data?.quote_validity_business_days ?? 12,
            })}
            confirmLabel={t("quotes.send")}
            onConfirm={() => send.mutate()}
          >
            <Send aria-hidden />
            {t("quotes.send")}
          </ConfirmButton>
          {/* La vista previa es de lo guardado (la genera la API): con cambios
              sin guardar enseñaría otra cosa. */}
          <PdfButton quoteId={quote.id} label={t("quotes.preview")} disabled={dirty || lines.length === 0} />
          <ConfirmButton
            variant="ghost"
            disabled={discard.isPending}
            title={t("quotes.discard")}
            description={t("quotes.confirmDiscard", { number: quote.version_no })}
            confirmLabel={t("quotes.discard")}
            destructive
            onConfirm={() => discard.mutate()}
          >
            {t("quotes.discard")}
          </ConfirmButton>
        </div>
      </CardContent>
    </Card>
  );
}

function LineEditor({
  line,
  number,
  invalid,
  rates,
  onChange,
  onRemove,
}: {
  line: LineDraft;
  number: number;
  invalid: boolean;
  rates: { id: string; name: string; hourly_price_cents: number }[];
  onChange: (patch: Partial<LineDraft>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const id = (field: string) => `${line.key}-${field}`;
  const field = (name: keyof LineDraft, label: string, props: { inputMode?: "decimal" } = {}) => (
    <div className="grid gap-1">
      <Label htmlFor={id(name)} className="text-xs">
        {label}
      </Label>
      <Input
        id={id(name)}
        value={line[name]}
        aria-invalid={invalid || undefined}
        onChange={(event) => onChange({ [name]: event.target.value })}
        {...props}
      />
    </div>
  );

  return (
    <li className={`grid gap-3 rounded-lg border p-3 ${invalid ? "border-destructive" : ""}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">
          {number}. {t(`quotes.kinds.${line.kind}`)}
        </span>
        <Button variant="ghost" size="sm" aria-label={t("quotes.removeLine", { number })} onClick={onRemove}>
          <Trash2 aria-hidden />
        </Button>
      </div>
      <div className="grid gap-3 md:grid-cols-[3fr_1fr_1fr_1fr_1fr]">
        <div className="grid gap-1">
          <Label htmlFor={id("description")} className="text-xs">
            {t("quotes.description")}
          </Label>
          <Input
            id={id("description")}
            value={line.description}
            list={line.kind === "labor" ? `${line.key}-rates` : undefined}
            aria-invalid={invalid || undefined}
            onChange={(event) => {
              // Elegir una tarifa de la lista copia también su precio (RF-38).
              const rate = line.kind === "labor" ? rates.find((r) => r.name === event.target.value) : undefined;
              onChange(
                rate
                  ? { description: rate.name, price: centsToInput(rate.hourly_price_cents) }
                  : { description: event.target.value },
              );
            }}
          />
          {line.kind === "labor" && (
            <datalist id={`${line.key}-rates`}>
              {rates.map((rate) => (
                <option key={rate.id} value={rate.name} />
              ))}
            </datalist>
          )}
        </div>
        {field("quantity", t(line.kind === "labor" ? "quotes.hours" : "quotes.quantity"), { inputMode: "decimal" })}
        {field("price", t(line.kind === "labor" ? "quotes.pricePerHour" : "quotes.unitPrice"), {
          inputMode: "decimal",
        })}
        {field("discount", t("quotes.lineDiscount"), { inputMode: "decimal" })}
        {field("vat", t("quotes.vatRate"), { inputMode: "decimal" })}
      </div>
      {line.kind === "part" && (
        <div className="grid gap-3 md:grid-cols-2">
          {field("reference", t("quotes.reference"))}
          <div className="grid gap-1">
            <Label htmlFor={id("condition")} className="text-xs">
              {t("quotes.condition")}
            </Label>
            <Select
              id={id("condition")}
              value={line.condition}
              onChange={(event) => onChange({ condition: event.target.value as PartCondition })}
            >
              {PART_CONDITIONS.map((condition) => (
                <option key={condition} value={condition}>
                  {t(`quotes.conditions.${condition}`)}
                </option>
              ))}
            </Select>
            {line.condition !== "new" && (
              <p className="text-muted-foreground text-xs">{t("quotes.conditionHint")}</p>
            )}
          </div>
        </div>
      )}
    </li>
  );
}
