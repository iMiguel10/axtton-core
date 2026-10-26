import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Field } from "@/shared/components/form/Field";
import { Select } from "@/shared/components/form/Select";
import { Button } from "@/shared/components/ui/button";
import { Label } from "@/shared/components/ui/label";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { FUELS, vehiclesApi, type Vehicle, type VehicleInput } from "./api";

const optionalInt = (min: number, max: number) =>
  z
    .string()
    .trim()
    .refine((v) => v === "" || (/^\d+$/.test(v) && +v >= min && +v <= max), "validation.number");

// Los mismos límites que el backend (schemas/vehicles.py); él vuelve a comprobarlos
// y además decide si la matrícula y el VIN son válidos una vez normalizados.
const schema = z.object({
  plate: z.string().trim().min(1, "validation.required").max(20),
  vin: z.string().trim().max(25),
  make: z.string().trim().max(60),
  model: z.string().trim().max(60),
  year: optionalInt(1900, 2100),
  fuel: z.union([z.literal(""), z.enum(FUELS)]),
  nextItvDate: z.string(),
  nextServiceDate: z.string(),
  nextServiceKm: optionalInt(1, 9_999_999),
});
type Values = z.infer<typeof schema>;

function toValues(vehicle?: Vehicle): Values {
  return {
    plate: vehicle?.plate ?? "",
    vin: vehicle?.vin ?? "",
    make: vehicle?.make ?? "",
    model: vehicle?.model ?? "",
    year: vehicle?.year?.toString() ?? "",
    fuel: vehicle?.fuel ?? "",
    nextItvDate: vehicle?.next_itv_date ?? "",
    nextServiceDate: vehicle?.next_service_date ?? "",
    nextServiceKm: vehicle?.next_service_km?.toString() ?? "",
  };
}

function toInput(values: Values): VehicleInput {
  const int = (v: string) => (v ? Number(v) : null);
  return {
    plate: values.plate,
    vin: values.vin || null,
    make: values.make || null,
    model: values.model || null,
    year: int(values.year),
    fuel: values.fuel || null,
    next_itv_date: values.nextItvDate || null,
    next_service_date: values.nextServiceDate || null,
    next_service_km: int(values.nextServiceKm),
  };
}

/** Lo que el taller ya ha escrito, como sugerencias de un <datalist> (RF-11). */
function useSuggestions(field: "make" | "model", value: string, make?: string) {
  const { workshopId } = useActiveWorkshop();
  const q = useDebouncedValue(value.trim());
  return (
    useQuery({
      queryKey: ["vehicle-suggestions", workshopId, field, q, make ?? ""],
      queryFn: () => vehiclesApi(workshopId).suggestions(field, q, make),
      staleTime: 60_000,
    }).data ?? []
  );
}

/**
 * Alta y edición de los datos de un vehículo (RF-11, RF-16). El titular no va
 * aquí: al crear, quien lo usa pone el selector en `before`; al editar, tiene su
 * propia operación. Al editar se le pone `key={vehicle.version}`, como a la
 * ficha del cliente.
 */
export function VehicleForm({
  vehicle,
  before,
  submitLabel,
  pending,
  canSubmit = true,
  onSubmit,
}: {
  vehicle?: Vehicle;
  before?: ReactNode;
  submitLabel: string;
  pending: boolean;
  canSubmit?: boolean;
  onSubmit: (input: VehicleInput) => void;
}) {
  const { t } = useTranslation();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(vehicle) });
  const { errors, isDirty } = form.formState;
  const message = (key?: string) => (key ? t(key) : undefined);
  const [make, model] = useWatch({ control: form.control, name: ["make", "model"] });
  const makes = useSuggestions("make", make);
  const models = useSuggestions("model", model, make.trim() || undefined);

  return (
    <form
      className="grid gap-4 md:grid-cols-2"
      onSubmit={form.handleSubmit((values) => onSubmit(toInput(values)))}
      noValidate
    >
      {before && <div className="md:col-span-2">{before}</div>}
      <Field
        id="vehicle-plate"
        label={t("vehicles.plate")}
        autoComplete="off"
        autoCapitalize="characters"
        error={message(errors.plate?.message)}
        {...form.register("plate")}
      />
      <Field
        id="vehicle-vin"
        label={t("vehicles.vinOptional")}
        autoComplete="off"
        autoCapitalize="characters"
        error={message(errors.vin?.message)}
        {...form.register("vin")}
      />
      <Field
        id="vehicle-make"
        label={t("vehicles.make")}
        autoComplete="off"
        list="vehicle-make-suggestions"
        {...form.register("make")}
      />
      <datalist id="vehicle-make-suggestions">
        {makes.map((make) => (
          <option key={make} value={make} />
        ))}
      </datalist>
      <Field
        id="vehicle-model"
        label={t("vehicles.model")}
        autoComplete="off"
        list="vehicle-model-suggestions"
        {...form.register("model")}
      />
      <datalist id="vehicle-model-suggestions">
        {models.map((model) => (
          <option key={model} value={model} />
        ))}
      </datalist>
      <Field
        id="vehicle-year"
        inputMode="numeric"
        label={t("vehicles.year")}
        error={message(errors.year?.message)}
        {...form.register("year")}
      />
      <div className="grid gap-1.5">
        <Label htmlFor="vehicle-fuel">{t("vehicles.fuel")}</Label>
        <Select id="vehicle-fuel" {...form.register("fuel")}>
          <option value="">—</option>
          {FUELS.map((fuel) => (
            <option key={fuel} value={fuel}>
              {t(`vehicles.fuels.${fuel}`)}
            </option>
          ))}
        </Select>
      </div>
      <fieldset className="grid gap-4 md:col-span-2 md:grid-cols-3">
        <legend className="text-muted-foreground mb-2 text-sm">{t("vehicles.dueDates")}</legend>
        <Field
          id="vehicle-itv"
          type="date"
          label={t("vehicles.nextItv")}
          {...form.register("nextItvDate")}
        />
        <Field
          id="vehicle-service-date"
          type="date"
          label={t("vehicles.nextServiceDate")}
          {...form.register("nextServiceDate")}
        />
        <Field
          id="vehicle-service-km"
          inputMode="numeric"
          label={t("vehicles.nextServiceKm")}
          error={message(errors.nextServiceKm?.message)}
          {...form.register("nextServiceKm")}
        />
      </fieldset>
      <div className="md:col-span-2">
        <Button
          type="submit"
          disabled={pending || !canSubmit || (vehicle !== undefined && !isDirty)}
        >
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
