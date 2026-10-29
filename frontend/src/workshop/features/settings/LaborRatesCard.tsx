import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { EmptyState } from "@/shared/components/EmptyState";
import { LinesSkeleton } from "@/shared/components/Loading";
import { notify } from "@/shared/components/Toaster";
import { SwitchFilter } from "@/shared/components/filters/Filters";
import { Field } from "@/shared/components/form/Field";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";
import { centsToInput, formatEur, parseEurToCents } from "@/shared/money";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { settingsApi, type LaborRate, type LaborRateInput } from "./api";

const schema = z.object({
  name: z.string().trim().min(1, "validation.required").max(100),
  price: z.string().refine((value) => parseEurToCents(value) !== null, "validation.amount"),
});
type Values = z.infer<typeof schema>;

/**
 * Tarifas de mano de obra con nombre, una por defecto (RF-02). Una línea de
 * presupuesto copia su nombre y su precio al usarla, así que cambiarlas no toca
 * presupuestos ya hechos (RF-38).
 */
export function LaborRatesCard() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = settingsApi(workshopId);
  const queryClient = useQueryClient();
  const [archived, setArchived] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const queryKey = ["labor-rates", workshopId, archived];
  const rates = useQuery({ queryKey, queryFn: () => api.rates(archived) });
  // Una sola mutación para las acciones de fila, como en empleados: el error
  // (un 409 si otro administrador la cambió) se enseña arriba de la lista.
  const action = useMutation({
    mutationFn: ({ run }: { run: () => Promise<unknown>; done: string }) => run(),
    onSuccess: (_, { done }) => {
      setEditing(null);
      notify(done);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["labor-rates", workshopId] }),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("rates.title")}</CardTitle>
        <CardDescription>{t("rates.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {!archived && (
          <RateForm
            submitLabel={t("rates.add")}
            pending={action.isPending}
            onSubmit={(input) => action.mutateAsync({ run: () => api.createRate(input), done: t("rates.added") })}
          />
        )}
        <SwitchFilter label={t("rates.showArchived")} checked={archived} onChange={setArchived} />
        {action.isError && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, action.error)}
          </p>
        )}
        {rates.isPending ? (
          <LinesSkeleton />
        ) : rates.isError ? (
          <p role="alert">{errorMessage(t, rates.error)}</p>
        ) : rates.data.length === 0 ? (
          <EmptyState
            icon={Clock}
            title={t(archived ? "rates.noneArchived" : "rates.none")}
            description={archived ? undefined : t("rates.noneHint")}
          />
        ) : (
          <ul className="divide-y">
            {rates.data.map((rate) =>
              editing === rate.id ? (
                <li key={rate.id} className="py-3">
                  <RateForm
                    rate={rate}
                    submitLabel={t("common.save")}
                    pending={action.isPending}
                    onCancel={() => setEditing(null)}
                    onSubmit={(input) =>
                      action.mutateAsync({ run: () => api.updateRate(rate, input), done: t("rates.saved") })
                    }
                  />
                </li>
              ) : (
                <li key={rate.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                  <div className="grid">
                    <span className="flex items-center gap-2 font-medium">
                      {rate.name}
                      {rate.is_default && <Badge variant="outline">{t("rates.default")}</Badge>}
                    </span>
                    <span className="text-muted-foreground text-sm tabular-nums">
                      {t("rates.perHour", { price: formatEur(rate.hourly_price_cents) })}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {archived ? (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={action.isPending}
                        onClick={() =>
                          action.mutate({ run: () => api.setArchived(rate, false), done: t("rates.unarchived") })
                        }
                      >
                        {t("rates.unarchive")}
                      </Button>
                    ) : (
                      <>
                        {!rate.is_default && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={action.isPending}
                            onClick={() =>
                              action.mutate({
                                run: () => api.updateRate(rate, { is_default: true }),
                                done: t("rates.saved"),
                              })
                            }
                          >
                            {t("rates.makeDefault")}
                          </Button>
                        )}
                        <Button variant="outline" size="sm" disabled={action.isPending} onClick={() => setEditing(rate.id)}>
                          {t("rates.edit")}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={action.isPending}
                          onClick={() =>
                            action.mutate({ run: () => api.setArchived(rate, true), done: t("rates.archived") })
                          }
                        >
                          {t("rates.archive")}
                        </Button>
                      </>
                    )}
                  </div>
                </li>
              ),
            )}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function RateForm({
  rate,
  submitLabel,
  pending,
  onSubmit,
  onCancel,
}: {
  rate?: LaborRate;
  submitLabel: string;
  pending: boolean;
  onSubmit: (input: LaborRateInput) => Promise<unknown>;
  onCancel?: () => void;
}) {
  const { t } = useTranslation();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: rate?.name ?? "",
      price: rate ? centsToInput(rate.hourly_price_cents) : "",
    },
  });
  const { errors } = form.formState;
  const id = rate?.id ?? "new";

  return (
    <form
      className="grid gap-3 sm:grid-cols-[2fr_1fr_auto] sm:items-end"
      onSubmit={form.handleSubmit(async (values) => {
        // Se vacía solo si se guardó: tras un 409 (nombre repetido) sigue lo escrito.
        // El error lo enseña la tarjeta.
        const saved = await onSubmit({ name: values.name, hourly_price_cents: parseEurToCents(values.price)! })
          .then(() => true)
          .catch(() => false);
        if (saved && !rate) form.reset();
      })}
      noValidate
    >
      <Field
        id={`rate-name-${id}`}
        label={t("rates.name")}
        placeholder={rate ? undefined : t("rates.namePlaceholder")}
        error={errors.name && t(errors.name.message ?? "")}
        {...form.register("name")}
      />
      <Field
        id={`rate-price-${id}`}
        inputMode="decimal"
        label={t("rates.price")}
        error={errors.price && t(errors.price.message ?? "")}
        {...form.register("price")}
      />
      <div className="flex gap-1">
        <Button type="submit" disabled={pending}>
          {submitLabel}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
        )}
      </div>
    </form>
  );
}
