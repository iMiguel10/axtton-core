import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { ordersApi, type OrderDetail, type ReceptionInput } from "./api";
import { formatDateTime, StatusBadge } from "./OrderBits";
import { ReceptionForm } from "./ReceptionForm";

const CLOSED = ["delivered", "cancelled"];

/**
 * Ficha de una orden (RF-20 a RF-25): vehículo, cliente, recepción, responsable
 * e historial de estados. Cambiar de estado llega en el paso 4 de F2.
 */
export function OrderDetailPage() {
  const { t } = useTranslation();
  const { orderId = "" } = useParams();
  const { workshopId, canManageOrders } = useActiveWorkshop();
  const api = ordersApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["order", workshopId, orderId];
  const order = useQuery({ queryKey, queryFn: () => api.get(orderId) });
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: ({ current, input }: { current: OrderDetail; input: ReceptionInput }) =>
      api.update(current, input),
    onMutate: () => setSaved(false),
    onSuccess: () => setSaved(true),
    // También tras un 409: se recarga lo último guardado, con su versión.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey }),
        queryClient.invalidateQueries({ queryKey: ["orders", workshopId] }),
      ]),
  });

  if (order.isPending) return <p>{t("common.loading")}</p>;
  if (order.isError) return <p role="alert">{errorMessage(t, order.error)}</p>;
  const current = order.data;
  const editable = canManageOrders && !CLOSED.includes(current.status);

  return (
    <section className="grid gap-4">
      <Link to="/orders" className="text-muted-foreground text-sm hover:underline">
        ← {t("orders.backToList")}
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-mono text-2xl font-semibold">{current.code}</h1>
        <StatusBadge status={current.status} unrepaired={current.unrepaired} />
        <span className="text-muted-foreground text-sm">{t(`orders.types.${current.type}`)}</span>
        {current.warranty_of && (
          <Link to={`/orders/${current.warranty_of.id}`} className="text-sm hover:underline">
            {t("orders.warrantyOf", { code: current.warranty_of.code })}
          </Link>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("orders.vehicle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <Link to={`/vehicles/${current.vehicle.id}`} className="font-mono font-medium hover:underline">
              {current.vehicle.plate}
            </Link>
            <p className="text-muted-foreground text-sm">
              {[current.vehicle.make, current.vehicle.model].filter(Boolean).join(" ") || "—"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("orders.client")}</CardTitle>
          </CardHeader>
          <CardContent>
            <Link to={`/clients/${current.client.id}`} className="font-medium hover:underline">
              {current.client.name}
            </Link>
            <p className="text-muted-foreground text-sm">{current.client.phone}</p>
            <p className="text-muted-foreground mt-1 text-xs">{t("orders.clientHint")}</p>
          </CardContent>
        </Card>
      </div>
      {save.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, save.error)}
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm">
          {t("orders.saved")}
        </p>
      )}
      <Card>
        <CardHeader>
          <CardTitle>{t("orders.reception")}</CardTitle>
        </CardHeader>
        <CardContent>
          {editable ? (
            <ReceptionForm
              key={current.version}
              order={current}
              submitLabel={t("common.save")}
              pending={save.isPending}
              onSubmit={(input) => save.mutate({ current, input })}
            />
          ) : (
            <ReceptionSummary order={current} />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("orders.history")}</CardTitle>
        </CardHeader>
        <CardContent>
          <History order={current} />
        </CardContent>
      </Card>
    </section>
  );
}

function ReceptionSummary({ order }: { order: OrderDetail }) {
  const { t, i18n } = useTranslation();
  const droppedOff = [order.dropped_off_by_name, order.dropped_off_by_phone]
    .filter(Boolean)
    .join(" · ");
  const rows: [string, string | null][] = [
    [t("orders.reason"), order.reason],
    [t("orders.odometer"), order.odometer_km?.toLocaleString(i18n.language) ?? null],
    [t("orders.expectedDelivery"), formatDateTime(order.expected_delivery_at, i18n.language)],
    [t("orders.responsible"), order.responsible?.name ?? null],
    [t("orders.droppedOffBy"), droppedOff || null],
    [t("orders.receptionNotes"), order.reception_notes],
  ];
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[max-content_1fr]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground text-sm">{label}</dt>
          <dd className="whitespace-pre-line">{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** El historial por `seq`, del primero al último: el último es el estado. */
function History({ order }: { order: OrderDetail }) {
  const { t, i18n } = useTranslation();
  return (
    <ol className="grid gap-3">
      {order.history.map((change) => (
        <li key={change.seq} className="grid gap-0.5 border-l-2 pl-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={change.to_status} />
            <span className="text-muted-foreground text-xs">{t(`orders.causes.${change.cause}`)}</span>
          </div>
          <span className="text-muted-foreground text-sm">
            {formatDateTime(change.created_at, i18n.language)}
            {" · "}
            {change.by_client ? t("orders.byClient") : (change.employee_name ?? "—")}
          </span>
          {change.note && <p className="text-sm whitespace-pre-line">{change.note}</p>}
        </li>
      ))}
    </ol>
  );
}
