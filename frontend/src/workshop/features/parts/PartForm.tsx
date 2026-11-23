import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Field } from "@/shared/components/form/Field";
import { Select } from "@/shared/components/form/Select";
import { Button } from "@/shared/components/ui/button";
import { Label } from "@/shared/components/ui/label";
import { Switch } from "@/shared/components/ui/switch";
import { bpToInput, centsToInput, parseEurToCents, parsePercentToBp } from "@/shared/money";
import { formatQuantity, parseQuantityOrZero } from "@/shared/quantity";

import { PART_CONDITIONS, type Part, type PartInput } from "./api";

const optional = (check: (value: string) => boolean) => (value: string) =>
  value.trim() === "" || check(value);

/** "24" → 24; vacío → null. Entre 4 y 120 meses (schemas/parts.py). */
function parseWarranty(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const months = Number(trimmed);
  return /^\d{1,3}$/.test(trimmed) && months >= 4 && months <= 120 ? months : null;
}

// Los mismos límites que el backend (schemas/parts.py); él vuelve a comprobarlos.
const schema = z.object({
  reference: z.string().trim().min(1, "validation.required").max(100),
  description: z.string().trim().min(1, "validation.required").max(300),
  brand: z.string().trim().max(100),
  costPrice: z.string().refine(optional((v) => parseEurToCents(v) !== null), "validation.amount"),
  salePrice: z.string().refine((v) => parseEurToCents(v) !== null, "validation.amount"),
  // Vacío al dar de alta: el IVA por defecto del taller.
  vat: z.string().refine(optional((v) => parsePercentToBp(v) !== null), "validation.percent"),
  condition: z.enum(PART_CONDITIONS),
  warranty: z.string().refine(optional((v) => parseWarranty(v) !== null), "validation.warranty"),
  tracksStock: z.boolean(),
  minStock: z.string().refine(optional((v) => parseQuantityOrZero(v) !== null), "validation.quantity"),
});
type Values = z.infer<typeof schema>;

function toValues(part?: Part): Values {
  return {
    reference: part?.reference ?? "",
    description: part?.description ?? "",
    brand: part?.brand ?? "",
    costPrice: part?.cost_price_cents == null ? "" : centsToInput(part.cost_price_cents),
    salePrice: part?.sale_price_cents == null ? "" : centsToInput(part.sale_price_cents),
    vat: part ? bpToInput(part.vat_bp) : "",
    condition: part?.part_condition ?? "new",
    warranty: part?.warranty_months == null ? "" : String(part.warranty_months),
    tracksStock: part?.tracks_stock ?? true,
    minStock: part?.min_stock == null ? "" : formatQuantity(part.min_stock),
  };
}

/** Lo escrito, como lo espera la API. Sin IVA, el alta toma el del taller. */
function toInput(values: Values): PartInput {
  const vat = values.vat.trim() === "" ? undefined : parsePercentToBp(values.vat)!;
  return {
    reference: values.reference,
    description: values.description,
    brand: values.brand || null,
    cost_price_cents: values.costPrice.trim() === "" ? null : parseEurToCents(values.costPrice),
    sale_price_cents: parseEurToCents(values.salePrice)!,
    ...(vat === undefined ? {} : { vat_bp: vat }),
    part_condition: values.condition,
    warranty_months: parseWarranty(values.warranty),
    tracks_stock: values.tracksStock,
    // Sin contar el stock no hay mínimo (RF-95).
    min_stock: values.tracksStock && values.minStock.trim() !== "" ? parseQuantityOrZero(values.minStock) : null,
  };
}

/**
 * Alta y edición de una pieza del catálogo (RF-90), solo para el administrador.
 * Al editar, quien lo usa le pone `key={part.version}`: tras un 409 la ficha se
 * recarga y el formulario vuelve a empezar desde lo último guardado.
 */
export function PartForm({
  part,
  submitLabel,
  pending,
  onSubmit,
}: {
  part?: Part;
  submitLabel: string;
  pending: boolean;
  onSubmit: (input: PartInput) => void;
}) {
  const { t } = useTranslation();
  const form = useForm<Values>({
    resolver: zodResolver(
      // Al editar, el IVA ya existe: no se puede vaciar.
      part ? schema.extend({ vat: z.string().refine((v) => parsePercentToBp(v) !== null, "validation.percent") }) : schema,
    ),
    defaultValues: toValues(part),
  });
  const { errors, isDirty } = form.formState;
  const message = (key?: string) => (key ? t(key) : undefined);
  const tracksStock = useWatch({ control: form.control, name: "tracksStock" });

  return (
    <form
      className="grid gap-4 md:grid-cols-2"
      onSubmit={form.handleSubmit((values) => onSubmit(toInput(values)))}
      noValidate
    >
      <Field
        id="part-reference"
        label={t("parts.reference")}
        autoComplete="off"
        error={message(errors.reference?.message)}
        {...form.register("reference")}
      />
      <Field
        id="part-brand"
        label={t("parts.brand")}
        autoComplete="off"
        error={message(errors.brand?.message)}
        {...form.register("brand")}
      />
      <div className="md:col-span-2">
        <Field
          id="part-description"
          label={t("parts.description")}
          autoComplete="off"
          error={message(errors.description?.message)}
          {...form.register("description")}
        />
      </div>
      <Field
        id="part-sale-price"
        inputMode="decimal"
        label={t("parts.salePrice")}
        error={message(errors.salePrice?.message)}
        {...form.register("salePrice")}
      />
      <Field
        id="part-cost-price"
        inputMode="decimal"
        label={t("parts.costPrice")}
        error={message(errors.costPrice?.message)}
        {...form.register("costPrice")}
      />
      <Field
        id="part-vat"
        inputMode="decimal"
        label={t("parts.vat")}
        placeholder={part ? undefined : "21"}
        error={message(errors.vat?.message)}
        {...form.register("vat")}
      />
      <div className="grid gap-1.5">
        <Label htmlFor="part-condition">{t("parts.condition")}</Label>
        <Select id="part-condition" {...form.register("condition")}>
          {PART_CONDITIONS.map((condition) => (
            <option key={condition} value={condition}>
              {t(`parts.conditions.${condition}`)}
            </option>
          ))}
        </Select>
        <p className="text-muted-foreground text-xs">{t("parts.conditionHint")}</p>
      </div>
      <div className="grid gap-1.5">
        <Field
          id="part-warranty"
          inputMode="numeric"
          label={t("parts.warranty")}
          error={message(errors.warranty?.message)}
          {...form.register("warranty")}
        />
        <p className="text-muted-foreground text-xs">{t("parts.warrantyHint")}</p>
      </div>
      <div className="flex items-start gap-3">
        <Controller
          control={form.control}
          name="tracksStock"
          render={({ field }) => (
            <Switch
              id="part-tracks-stock"
              checked={field.value}
              onCheckedChange={(checked) => field.onChange(checked)}
            />
          )}
        />
        <div className="grid gap-0.5">
          <Label htmlFor="part-tracks-stock">{t("parts.tracksStock")}</Label>
          <p className="text-muted-foreground text-xs">{t("parts.tracksStockHint")}</p>
        </div>
      </div>
      {tracksStock && (
        <div className="grid gap-1.5">
          <Field
            id="part-min-stock"
            inputMode="decimal"
            label={t("parts.minStock")}
            error={message(errors.minStock?.message)}
            {...form.register("minStock")}
          />
          <p className="text-muted-foreground text-xs">{t("parts.minStockHint")}</p>
        </div>
      )}
      <div className="md:col-span-2">
        <Button type="submit" disabled={pending || (part !== undefined && !isDirty)}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
