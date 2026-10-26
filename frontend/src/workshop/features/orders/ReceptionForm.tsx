import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Field } from "@/shared/components/form/Field";
import { Select } from "@/shared/components/form/Select";
import { Textarea } from "@/shared/components/form/Textarea";
import { Button } from "@/shared/components/ui/button";
import { Label } from "@/shared/components/ui/label";

import { employeesApi } from "../employees/api";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import type { OrderDetail, ReceptionInput } from "./api";

const schema = z.object({
  odometerKm: z
    .string()
    .trim()
    .refine((v) => v === "" || (/^\d+$/.test(v) && +v <= 9_999_999), "validation.number"),
  reason: z.string().trim().max(2000),
  expectedDelivery: z.string(),
  droppedOffByName: z.string().trim().max(200),
  droppedOffByPhone: z.string().trim().max(30),
  receptionNotes: z.string().trim().max(2000),
  responsibleId: z.string(),
});
type Values = z.infer<typeof schema>;

/** "2026-11-02T18:00" en la hora del navegador, para un <input type="datetime-local">. */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toValues(order?: OrderDetail): Values {
  return {
    odometerKm: order?.odometer_km?.toString() ?? "",
    reason: order?.reason ?? "",
    expectedDelivery: toLocalInput(order?.expected_delivery_at ?? null),
    droppedOffByName: order?.dropped_off_by_name ?? "",
    droppedOffByPhone: order?.dropped_off_by_phone ?? "",
    receptionNotes: order?.reception_notes ?? "",
    responsibleId: order?.responsible?.id ?? "",
  };
}

function toInput(values: Values): ReceptionInput {
  return {
    odometer_km: values.odometerKm ? Number(values.odometerKm) : null,
    reason: values.reason || null,
    // El navegador interpreta la hora en su zona; el ISO lleva el desfase, así
    // que el servidor sabe qué instante es (la API rechaza horas sin zona).
    expected_delivery_at: values.expectedDelivery
      ? new Date(values.expectedDelivery).toISOString()
      : null,
    dropped_off_by_name: values.droppedOffByName || null,
    dropped_off_by_phone: values.droppedOffByPhone || null,
    reception_notes: values.receptionNotes || null,
    responsible_employee_id: values.responsibleId || null,
  };
}

/**
 * Los datos de recepción y el responsable (RF-20, RF-25). Para abrir una orden,
 * quien lo usa pone delante el vehículo y el tipo (`before`); para editarla, le
 * pone `key={order.version}`.
 */
export function ReceptionForm({
  order,
  before,
  submitLabel,
  pending,
  canSubmit = true,
  onSubmit,
}: {
  order?: OrderDetail;
  before?: ReactNode;
  submitLabel: string;
  pending: boolean;
  canSubmit?: boolean;
  onSubmit: (input: ReceptionInput) => void;
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  // Solo quien abre y edita órdenes (el administrador) llega aquí, y es quien
  // puede listar los empleados.
  const employees = useQuery({
    queryKey: ["employees", workshopId],
    queryFn: () => employeesApi(workshopId).list(),
  });
  const candidates = (employees.data ?? []).filter(
    (e) => e.active || e.id === order?.responsible?.id,
  );
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(order) });
  const { errors, isDirty } = form.formState;

  return (
    <form
      className="grid gap-4 md:grid-cols-2"
      onSubmit={form.handleSubmit((values) => onSubmit(toInput(values)))}
      noValidate
    >
      {before && <div className="grid gap-4 md:col-span-2 md:grid-cols-2">{before}</div>}
      <div className="grid gap-1.5 md:col-span-2">
        <Label htmlFor="order-reason">{t("orders.reason")}</Label>
        <Textarea id="order-reason" {...form.register("reason")} />
      </div>
      <Field
        id="order-odometer"
        inputMode="numeric"
        label={t("orders.odometer")}
        error={errors.odometerKm?.message && t(errors.odometerKm.message)}
        {...form.register("odometerKm")}
      />
      <Field
        id="order-expected"
        type="datetime-local"
        label={t("orders.expectedDelivery")}
        {...form.register("expectedDelivery")}
      />
      <div className="grid gap-1.5">
        <Label htmlFor="order-responsible">{t("orders.responsible")}</Label>
        <Select id="order-responsible" {...form.register("responsibleId")}>
          <option value="">{t("orders.unassigned")}</option>
          {candidates.map((employee) => (
            <option key={employee.id} value={employee.id}>
              {employee.name}
            </option>
          ))}
        </Select>
      </div>
      <div />
      <Field
        id="order-dropped-name"
        label={t("orders.droppedOffByName")}
        autoComplete="off"
        {...form.register("droppedOffByName")}
      />
      <Field
        id="order-dropped-phone"
        type="tel"
        label={t("orders.droppedOffByPhone")}
        autoComplete="off"
        {...form.register("droppedOffByPhone")}
      />
      <div className="grid gap-1.5 md:col-span-2">
        <Label htmlFor="order-reception-notes">{t("orders.receptionNotes")}</Label>
        <Textarea id="order-reception-notes" {...form.register("receptionNotes")} />
        <p className="text-muted-foreground text-xs">{t("orders.receptionNotesHint")}</p>
      </div>
      <div className="md:col-span-2">
        <Button type="submit" disabled={pending || !canSubmit || (order !== undefined && !isDirty)}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
