import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { DetailSkeleton, LinesSkeleton } from "@/shared/components/Loading";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { When } from "@/shared/components/When";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/components/ui/tabs";
import { notify } from "@/shared/components/Toaster";
import { errorMessage } from "@/shared/lib/errors";
import { cn } from "@/shared/lib/utils";
import { useDates } from "@/shared/lib/dates";

import { clientName } from "../clients/clientName";
import { usePageCrumb } from "../layout/PageCrumb";
import { QuotesSection } from "../quotes/QuotesSection";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { ordersApi, type OrderDetail, type ReceptionInput } from "./api";
import { StatusBadge } from "./OrderBits";
import { ReceptionForm } from "./ReceptionForm";
import { PaymentCard } from "./PaymentCard";
import { StatusCard } from "./StatusCard";
import { WorklogSection } from "./WorklogSection";

const CLOSED = ["delivered", "cancelled"];
const TABS = ["work", "diagnosis", "quotes", "notes", "reception", "history"] as const;

/**
 * Ficha de una orden (RF-20 a RF-25): vehículo, cliente, recepción, responsable
 * estado (con lo que quien mira puede hacer) e historial.
 */
export function OrderDetailPage() {
  const { t } = useTranslation();
  const { orderId = "" } = useParams();
  // ?tab=quotes abre directamente una pestaña: lo usa el listado de presupuestos.
  const [search] = useSearchParams();
  const initialTab = TABS.find((tab) => tab === search.get("tab")) ?? "work";
  const { workshopId, canManageOrders } = useActiveWorkshop();
  const api = ordersApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["order", workshopId, orderId];
  const order = useQuery({ queryKey, queryFn: () => api.get(orderId) });

  // También tras un 409: se recarga lo último guardado, con su versión.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ["orders", workshopId] }),
    ]);
  const save = useMutation({
    mutationFn: ({ current, input }: { current: OrderDetail; input: ReceptionInput }) =>
      api.update(current, input),
    onSuccess: () => notify(t("orders.saved")),
    onSettled: refresh,
  });

  // Un fallo al recargar (sin conexión) no se lleva la ficha ya cargada: debajo
  // están los borradores que se están escribiendo (RNF-22).
  usePageCrumb(order.data?.code);
  if (!order.data) {
    return order.isError ? <p role="alert">{errorMessage(t, order.error)}</p> : <DetailSkeleton />;
  }
  const current = order.data;
  const editable = canManageOrders && !CLOSED.includes(current.status);

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="tabular-nums text-2xl font-semibold">{current.code}</h1>
        <StatusBadge status={current.status} unrepaired={current.unrepaired} />
        <span className="text-muted-foreground text-sm">{t(`orders.types.${current.type}`)}</span>
        {current.warranty_of && (
          <Link to={`/orders/${current.warranty_of.id}`} className="link text-sm">
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
            <Link to={`/vehicles/${current.vehicle.id}`} className="link tabular-nums">
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
            <Link to={`/clients/${current.client.id}`} className="link">
              {clientName(t, current.client.name)}
            </Link>
            <p className="text-muted-foreground text-sm">{current.client.phone}</p>
            <p className="text-muted-foreground mt-1 text-xs">{t("orders.clientHint")}</p>
          </CardContent>
        </Card>
      </div>
      <StatusCard order={current} onChanged={refresh} />
      {CLOSED.includes(current.status) && <PaymentCard order={current} onChanged={refresh} />}
      {/* El resto, en pestañas: en el móvil del mecánico (RNF-20) la ficha entera
          era una página interminable. Trabajos va primero porque es lo que más
          se usa en el taller. `keepMounted`: cambiar de pestaña no desmonta los
          formularios, así que no se pierde lo que se está escribiendo ni la
          versión desde la que se edita el diagnóstico. */}
      <WorklogSection
        orderId={current.id}
        orderCode={current.code}
        closed={CLOSED.includes(current.status)}
        layout={(parts) => (
          <Tabs defaultValue={initialTab} className="min-w-0">
            <div className="-mx-4 min-w-0 overflow-x-auto overflow-y-hidden px-4 pb-1.5 md:mx-0 md:px-0">
              <TabsList>
                <TabsTrigger value="work">
                  {t("worklog.workTab")}
                  {parts && <Count value={parts.counts.work} />}
                </TabsTrigger>
                <TabsTrigger value="diagnosis">{t("worklog.diagnosisTab")}</TabsTrigger>
                <TabsTrigger value="quotes">{t("quotes.tab")}</TabsTrigger>
                <TabsTrigger value="notes">
                  {t("worklog.notesTab")}
                  {parts && <Count value={parts.counts.notes} />}
                </TabsTrigger>
                <TabsTrigger value="reception">{t("orders.reception")}</TabsTrigger>
                <TabsTrigger value="history">{t("orders.historyTab")}</TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="work" keepMounted>
              {parts?.work ?? <LinesSkeleton lines={4} />}
            </TabsContent>
            <TabsContent value="diagnosis" keepMounted>
              {parts?.diagnosis ?? <LinesSkeleton lines={4} />}
            </TabsContent>
            {/* keepMounted también aquí: el borrador del presupuesto vive en el
                navegador hasta que se guarda. */}
            <TabsContent value="quotes" keepMounted>
              <QuotesSection orderId={current.id} closed={CLOSED.includes(current.status)} />
            </TabsContent>
            <TabsContent value="notes" keepMounted>
              {parts?.notes ?? <LinesSkeleton lines={4} />}
            </TabsContent>
            <TabsContent value="reception" keepMounted className="grid gap-4">
              {save.isError && (
                <p role="alert" className="text-destructive text-sm">
                  {errorMessage(t, save.error)}
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
            </TabsContent>
            <TabsContent value="history">
              <Card>
                <CardHeader>
                  <CardTitle>{t("orders.history")}</CardTitle>
                </CardHeader>
                <CardContent>
                  <History order={current} />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        )}
      />
    </section>
  );
}

function ReceptionSummary({ order }: { order: OrderDetail }) {
  const { t, i18n } = useTranslation();
  const dates = useDates();
  const droppedOff = [order.dropped_off_by_name, order.dropped_off_by_phone]
    .filter(Boolean)
    .join(" · ");
  const rows: [string, string | null][] = [
    [t("orders.reason"), order.reason],
    [t("orders.odometer"), order.odometer_km?.toLocaleString(i18n.language) ?? null],
    [t("orders.expectedDelivery"), dates.dateTime(order.expected_delivery_at)],
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
  const { t } = useTranslation();
  // Lo último arriba: es lo que se busca al abrirlo. El orden sigue siendo el
  // de `seq` (invariante 5), solo que al revés.
  const changes = [...order.history].reverse();
  return (
    <ol className="relative grid gap-5 pl-6">
      {/* La línea del tiempo, detrás de los puntos. */}
      <span aria-hidden className="bg-border absolute top-2 bottom-2 left-[7px] w-px" />
      {changes.map((change, index) => (
        <li key={change.seq} className="relative grid gap-1">
          <span
            aria-hidden
            className={cn(
              "ring-background absolute top-1 -left-6 size-[15px] rounded-full border-4 ring-4",
              STATUS_DOT[change.to_status],
            )}
          />
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={change.to_status} unrepaired={index === 0 && order.unrepaired} />
            <span className="text-muted-foreground text-xs">{t(`orders.causes.${change.cause}`)}</span>
          </div>
          <span className="text-muted-foreground text-sm">
            <When iso={change.created_at} />
            {" · "}
            {change.by_client ? t("orders.byClient") : (change.employee_name ?? "—")}
          </span>
          {change.note && (
            <p className="bg-muted/60 rounded-lg px-3 py-2 text-sm whitespace-pre-line">{change.note}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

/** Cuántos hay, en la pestaña: se ve sin abrirla si hay notas o trabajos. */
function Count({ value }: { value: number }) {
  if (value === 0) return null;
  return (
    <span className="bg-muted text-muted-foreground rounded-full px-1.5 text-xs tabular-nums">
      {value}
    </span>
  );
}

// El punto de cada cambio, del color de su estado (los mismos tokens que StatusBadge).
const STATUS_DOT: Record<OrderDetail["status"], string> = {
  received: "border-status-received bg-background",
  diagnosing: "border-status-diagnosing bg-background",
  pending_approval: "border-status-pending-approval bg-background",
  approved: "border-status-approved bg-background",
  in_repair: "border-status-in-repair bg-background",
  waiting_parts: "border-status-waiting-parts bg-background",
  ready: "border-status-ready bg-background",
  delivered: "border-status-delivered bg-background",
  cancelled: "border-status-cancelled bg-background",
};
