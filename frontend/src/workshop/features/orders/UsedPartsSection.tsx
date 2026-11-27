import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Package } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/shared/components/EmptyState";
import { Field } from "@/shared/components/form/Field";
import { LinesSkeleton } from "@/shared/components/Loading";
import { notify } from "@/shared/components/Toaster";
import { SearchInput } from "@/shared/components/filters/Filters";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { ConfirmButton } from "@/shared/components/ConfirmButton";
import { apiRequest } from "@/shared/lib/apiClient";
import { useDates } from "@/shared/lib/dates";
import { errorMessage } from "@/shared/lib/errors";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { formatQuantity, parseQuantity } from "@/shared/quantity";

import { partsApi, type Part, type PartCondition } from "../parts/api";
import { useActiveWorkshop } from "../session/ActiveWorkshop";

/** Una pieza montada en la orden (RF-93), con lo que se copió de la pieza al montarla. */
export type UsedPart = {
  id: string;
  part_id: string;
  reference: string;
  description: string;
  part_condition: PartCondition;
  warranty_months: number | null;
  quantity: string;
  employee_id: string;
  employee_name: string;
  created_at: string;
  removed_at: string | null;
  removed_by_name: string | null;
  removable: boolean;
};

/** Cuelga de la clave de la orden: lo que recarga la ficha, la recarga también. */
export function usedPartsKey(workshopId: string, orderId: string) {
  return ["order", workshopId, orderId, "used-parts"];
}

export function useUsedParts(orderId: string) {
  const { workshopId } = useActiveWorkshop();
  return useQuery({
    queryKey: usedPartsKey(workshopId, orderId),
    queryFn: () =>
      apiRequest<UsedPart[]>(`/workshop/orders/${orderId}/used-parts`, { method: "GET", workshopId }),
  });
}

/**
 * Las piezas montadas en una orden (F7 paso 3). Las anotan el mecánico y el
 * administrador; cada una que cuenta su stock saca su unidad del libro. Quitar
 * una anotada por error la marca y devuelve el stock: nada se borra.
 */
export function UsedPartsSection({ orderId, closed }: { orderId: string; closed: boolean }) {
  const { t } = useTranslation();
  const dates = useDates();
  const { workshopId } = useActiveWorkshop();
  const used = useUsedParts(orderId);
  const queryClient = useQueryClient();
  // Lo que cambia con una pieza montada: la orden (su actividad), sus piezas,
  // y el stock y el historial de la pieza.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["order", workshopId, orderId] }),
      queryClient.invalidateQueries({ queryKey: ["parts", workshopId] }),
      queryClient.invalidateQueries({ queryKey: ["part", workshopId] }),
      queryClient.invalidateQueries({ queryKey: ["part-movements", workshopId] }),
    ]);
  const remove = useMutation({
    mutationFn: (usedId: string) =>
      apiRequest<void>(`/workshop/orders/${orderId}/used-parts/${usedId}/remove`, {
        method: "POST",
        workshopId,
      }),
    onSuccess: () => notify(t("usedParts.removed")),
    onSettled: refresh,
  });

  if (!used.data) {
    return used.isError ? (
      <p role="alert" className="text-destructive text-sm">
        {errorMessage(t, used.error)}
      </p>
    ) : (
      <LinesSkeleton lines={3} />
    );
  }

  return (
    <div className="grid gap-4">
      {!closed && <MountForm orderId={orderId} refresh={refresh} />}
      {remove.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, remove.error)}
        </p>
      )}
      {used.data.length === 0 ? (
        <EmptyState icon={Package} title={t("usedParts.empty")} />
      ) : (
        <ul className="divide-y rounded-lg border">
          {used.data.map((part) => (
            <li
              key={part.id}
              className={`flex flex-wrap items-start gap-x-4 gap-y-1 p-3 ${part.removed_at ? "opacity-60" : ""}`}
            >
              <div className="grid min-w-0 flex-1 gap-0.5">
                <span className={part.removed_at ? "line-through" : "font-medium"}>
                  <span className="tabular-nums">{formatQuantity(part.quantity)} × </span>
                  <Link to={`/parts/${part.part_id}`} className="link">
                    {part.description}
                  </Link>
                </span>
                <span className="text-muted-foreground text-sm">
                  {[
                    part.reference,
                    part.part_condition !== "new" ? t(`parts.conditions.${part.part_condition}`) : null,
                    part.warranty_months !== null
                      ? t("parts.warrantyMonths", { count: part.warranty_months })
                      : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                <span className="text-muted-foreground text-xs">
                  {part.removed_at
                    ? t("usedParts.removedBy", {
                        name: part.removed_by_name,
                        date: dates.dateTime(part.removed_at),
                      })
                    : t("usedParts.mountedBy", {
                        name: part.employee_name,
                        date: dates.dateTime(part.created_at),
                      })}
                </span>
              </div>
              {part.removed_at && <Badge variant="secondary">{t("usedParts.removedBadge")}</Badge>}
              {part.removable && (
                <ConfirmButton
                  variant="ghost"
                  size="sm"
                  disabled={remove.isPending}
                  title={t("usedParts.remove")}
                  description={t("usedParts.confirmRemove", { name: part.description })}
                  confirmLabel={t("usedParts.remove")}
                  onConfirm={() => remove.mutate(part.id)}
                >
                  {t("usedParts.remove")}
                </ConfirmButton>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Elegir una pieza del catálogo y cuántas se montan. Solo del catálogo
 * (decidido por el usuario al planificar F7): si falta, la da de alta el
 * administrador. */
function MountForm({ orderId, refresh }: { orderId: string; refresh: () => Promise<unknown> }) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search);
  const [chosen, setChosen] = useState<Part | null>(null);
  const [quantity, setQuantity] = useState("1");
  const [invalid, setInvalid] = useState(false);
  const results = useQuery({
    queryKey: ["parts", workshopId, { q, archived: false, alert: false, picker: true }],
    queryFn: () => partsApi(workshopId).list({ q, archived: false, alert: false }, 0),
    enabled: chosen === null && q.trim().length > 0,
  });
  const mount = useMutation({
    mutationFn: (part: Part) =>
      apiRequest<{ id: string }>(`/workshop/orders/${orderId}/used-parts`, {
        method: "POST",
        workshopId,
        body: { part_id: part.id, quantity: parseQuantity(quantity) },
      }),
    onSuccess: () => {
      notify(t("usedParts.mounted"));
      setChosen(null);
      setSearch("");
      setQuantity("1");
    },
    onSettled: refresh,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!chosen) return;
    if (parseQuantity(quantity) === null) return setInvalid(true);
    setInvalid(false);
    mount.mutate(chosen);
  };

  return (
    <form className="bg-muted/40 grid gap-3 rounded-lg p-3" onSubmit={submit} noValidate>
      {chosen === null ? (
        <>
          <SearchInput
            aria-label={t("usedParts.search")}
            placeholder={t("usedParts.searchPlaceholder")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {results.data && (
            results.data.parts.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("usedParts.noResults")}</p>
            ) : (
              <ul className="grid gap-1">
                {results.data.parts.slice(0, 8).map((part) => (
                  <li key={part.id}>
                    <button
                      type="button"
                      className="hover:bg-muted flex w-full flex-wrap items-center gap-x-3 rounded-md px-2 py-1.5 text-left"
                      onClick={() => setChosen(part)}
                    >
                      <span className="font-medium">{part.description}</span>
                      <span className="text-muted-foreground font-mono text-xs">{part.reference}</span>
                      {part.stock !== null && (
                        <span className="text-muted-foreground ml-auto text-xs tabular-nums">
                          {t("usedParts.inStock", { quantity: formatQuantity(part.stock) })}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )
          )}
        </>
      ) : (
        <div className="flex flex-wrap items-end gap-3">
          <div className="grid gap-0.5">
            <span className="font-medium">{chosen.description}</span>
            <span className="text-muted-foreground font-mono text-xs">{chosen.reference}</span>
          </div>
          <div className="w-28">
            <Field
              id="used-part-quantity"
              inputMode="decimal"
              label={t("usedParts.quantity")}
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              error={invalid ? t("validation.quantity") : undefined}
            />
          </div>
          <Button type="submit" size="sm" disabled={mount.isPending}>
            {t("usedParts.mount")}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setChosen(null)}>
            {t("usedParts.pickAnother")}
          </Button>
        </div>
      )}
      {mount.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, mount.error)}
        </p>
      )}
    </form>
  );
}
