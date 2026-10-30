import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmButton } from "@/shared/components/ConfirmButton";
import { EmptyState } from "@/shared/components/EmptyState";
import { LinesSkeleton } from "@/shared/components/Loading";
import { notify } from "@/shared/components/Toaster";
import { Select } from "@/shared/components/form/Select";
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
import {
  LINE_KINDS,
  PART_CONDITIONS,
  quotesApi,
  type DiscountKind,
  type DraftInput,
  type LineKind,
  type PartCondition,
  type Quote,
  type QuoteTotals,
} from "./api";

/**
 * Los presupuestos de una orden (RF-30 a RF-32): las versiones, de la más nueva
 * a la más antigua, y el borrador editable para quien los prepara. Los importes
 * los calcula siempre la API: el navegador solo los pinta (RNF-14).
 */
export function QuotesSection({ orderId, closed }: { orderId: string; closed: boolean }) {
  const { t } = useTranslation();
  const { workshopId, canManageQuotes } = useActiveWorkshop();
  const api = quotesApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["quotes", workshopId, orderId];
  const quotes = useQuery({ queryKey, queryFn: () => api.list(orderId) });
  const create = useMutation({
    mutationFn: () => api.create(orderId),
    onSettled: () => queryClient.invalidateQueries({ queryKey }),
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
            <DraftEditor key={quote.id} quote={quote} queryKey={queryKey} />
          ) : (
            <QuoteCard key={quote.id} quote={quote} />
          ),
        )
      )}
    </div>
  );
}

function QuoteHeader({ quote }: { quote: Quote }) {
  const { t } = useTranslation();
  const dates = useDates();
  return (
    <CardHeader>
      <CardTitle className="flex flex-wrap items-center gap-2">
        {t("quotes.version", { number: quote.version_no })}
        <Badge variant={quote.status === "draft" ? "outline" : "secondary"}>
          {t(`quotes.statuses.${quote.status}`)}
        </Badge>
      </CardTitle>
      <CardDescription>
        {quote.sent_at
          ? t("quotes.sentOn", {
              sent: dates.dateTime(quote.sent_at),
              until: dates.dateTime(quote.valid_until),
            })
          : t("quotes.draftHint")}
      </CardDescription>
    </CardHeader>
  );
}

/** Una versión que ya no se edita: lo que se envió, tal como se guardó. */
function QuoteCard({ quote }: { quote: Quote }) {
  const { t } = useTranslation();
  return (
    <Card>
      <QuoteHeader quote={quote} />
      <CardContent className="grid gap-4">
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
      </CardContent>
    </Card>
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

/** Lo escrito, pasado a lo que espera la API; o la lista de líneas con errores. */
function toInput(lines: LineDraft[], discount: Discount): DraftInput | { invalid: Set<string> } {
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
  return invalid.size ? { invalid } : { lines: parsed, global_discount: globalDiscount };
}

function DraftEditor({ quote, queryKey }: { quote: Quote; queryKey: unknown[] }) {
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
  // La versión desde la que se edita: guardar la sube, y un 409 avisa de que
  // otra persona guardó antes (RNF-15).
  const [baseVersion, setBaseVersion] = useState(quote.version);
  const [dirty, setDirty] = useState(false);
  const [invalid, setInvalid] = useState<Set<string>>(new Set());

  const refresh = () => queryClient.invalidateQueries({ queryKey });
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
    const input = toInput(lines, discount);
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

        {invalid.size > 0 && (
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
          (save.isError || discard.isError) && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(t, save.error ?? discard.error)}
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

        <div className="flex flex-wrap gap-2">
          <Button disabled={save.isPending || !dirty} onClick={() => submit()}>
            {t("common.save")}
          </Button>
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
