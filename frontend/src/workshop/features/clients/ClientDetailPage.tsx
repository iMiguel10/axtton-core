import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Car } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { EmptyState } from "@/shared/components/EmptyState";
import { ConfirmButton } from "@/shared/components/ConfirmButton";
import { DetailSkeleton, LinesSkeleton } from "@/shared/components/Loading";
import { Badge } from "@/shared/components/ui/badge";
import { Button, buttonVariants } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Input } from "@/shared/components/ui/input";
import { Label } from "@/shared/components/ui/label";
import { notify } from "@/shared/components/Toaster";
import { errorMessage } from "@/shared/lib/errors";
import { useDates } from "@/shared/lib/dates";

import { clientName } from "./clientName";
import { usePageCrumb } from "../layout/PageCrumb";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { RelatedOrders } from "../orders/OrderBits";
import { vehiclesApi } from "../vehicles/api";
import { clientsApi, type Client, type ClientInput } from "./api";
import { ClientForm } from "./ClientForm";

/** Ficha de un cliente (RF-10): editable para quien gestiona clientes, de solo
 * lectura para el mecánico (especificación §3). */
export function ClientDetailPage() {
  const { t } = useTranslation();
  const dates = useDates();
  const { clientId = "" } = useParams();
  const { workshopId, canManageClients } = useActiveWorkshop();
  const api = clientsApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["client", workshopId, clientId];
  const client = useQuery({ queryKey, queryFn: () => api.get(clientId) });

  // Haya ido bien o no (un 409 si otra persona guardó antes), se vuelve a pedir
  // la ficha: así el formulario tiene la versión al día y lo último guardado.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ["clients", workshopId] }),
    ]);
  const save = useMutation({
    mutationFn: ({ current, input }: { current: Client; input: ClientInput }) =>
      api.update(current, input),
    onSuccess: () => notify(t("clients.saved")),
    onSettled: refresh,
  });
  const archive = useMutation({
    mutationFn: (current: Client) => api.setArchived(current, current.archived_at === null),
    onSettled: refresh,
  });

  usePageCrumb(client.data ? clientName(t, client.data.name) : null);
  if (client.isPending) return <DetailSkeleton />;
  if (client.isError) return <p role="alert">{errorMessage(t, client.error)}</p>;
  const current = client.data;
  const failed = save.error ?? archive.error;

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-semibold">{clientName(t, current.name)}</h1>
        {current.archived_at && <Badge variant="secondary">{t("clients.archived")}</Badge>}
        {canManageClients &&
          !current.anonymized_at &&
          (current.archived_at ? (
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              disabled={archive.isPending}
              onClick={() => archive.mutate(current)}
            >
              {t("clients.unarchive")}
            </Button>
          ) : (
            // Archivar pide confirmación; desarchivar, no: no se pierde nada.
            <ConfirmButton
              variant="outline"
              size="sm"
              className="ml-auto"
              disabled={archive.isPending}
              title={t("clients.archive")}
              description={t("clients.confirmArchive", { name: current.name })}
              confirmLabel={t("clients.archive")}
              onConfirm={() => archive.mutate(current)}
            >
              {t("clients.archive")}
            </ConfirmButton>
          ))}
      </div>
      {failed && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, failed)}
        </p>
      )}
      {current.anonymized_at && (
        <p role="status" className="bg-muted rounded-lg p-3 text-sm">
          {t("clients.anonymizedNotice", { date: dates.date(current.anonymized_at) })}
        </p>
      )}
      <Card>
        <CardContent>
          {canManageClients && !current.anonymized_at ? (
            <ClientForm
              // Con otra versión, el formulario vuelve a empezar desde lo guardado.
              key={current.version}
              client={current}
              submitLabel={t("common.save")}
              pending={save.isPending}
              onSubmit={(input) => save.mutate({ current, input })}
            />
          ) : (
            <ClientSummary client={current} />
          )}
        </CardContent>
      </Card>
      <ClientVehicles client={current} canAdd={canManageClients} />
      <Card>
        <CardHeader>
          <CardTitle>{t("clients.orders")}</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Las órdenes de las que es cliente: las abiertas mientras era titular. */}
          <RelatedOrders filters={{ clientId: current.id }} show={{ vehicle: true }} />
        </CardContent>
      </Card>
      {canManageClients && !current.anonymized_at && <AnonymizeCard client={current} onDone={refresh} />}
    </section>
  );
}

/** Los vehículos de los que es titular hoy (RF-12). Los que tuvo antes salen en
 * la ficha de cada vehículo, con sus periodos. */
function ClientVehicles({ client, canAdd }: { client: Client; canAdd: boolean }) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const vehicles = useQuery({
    queryKey: ["vehicles", workshopId, { ownerId: client.id }],
    queryFn: () => vehiclesApi(workshopId).list({ ownerId: client.id }),
  });
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("clients.vehicles")}</CardTitle>
        {canAdd && client.archived_at === null && (
          <Link
            to={`/vehicles/new?owner=${client.id}`}
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            {t("vehicles.new")}
          </Link>
        )}
      </CardHeader>
      <CardContent>
        {vehicles.isPending ? (
          <LinesSkeleton />
        ) : vehicles.isError ? (
          <p role="alert">{errorMessage(t, vehicles.error)}</p>
        ) : vehicles.data.length === 0 ? (
          <EmptyState compact icon={Car} title={t("clients.noVehicles")} />
        ) : (
          <ul className="grid gap-1">
            {vehicles.data.map((vehicle) => (
              <li key={vehicle.id}>
                <Link to={`/vehicles/${vehicle.id}`} className="link">
                  <span className="tabular-nums font-medium">{vehicle.plate}</span>
                  {(vehicle.make || vehicle.model) && (
                    <span className="text-muted-foreground">
                      {" · "}
                      {[vehicle.make, vehicle.model].filter(Boolean).join(" ")}
                    </span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ClientSummary({ client }: { client: Client }) {
  const { t } = useTranslation();
  const rows: [string, string | null][] = [
    [t("clients.kind"), t(`clients.kinds.${client.kind}`)],
    [t("clients.phone"), client.phone],
    [t("clients.email"), client.email],
    [t("clients.taxId"), client.tax_id],
    [t("clients.language"), t(`clients.languages.${client.language}`)],
    [t("clients.address"), client.address],
    [t("clients.notes"), client.notes],
  ];
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[max-content_1fr]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground text-sm">{label}</dt>
          <dd className="whitespace-pre-line">{value || "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Borrar a un cliente que lo pide (RF-15). Es irreversible, así que no basta un
 * clic ni un `confirm`: hay que escribir su nombre. Con una orden abierta, el
 * servidor lo rechaza (esa orden aún necesita a quién avisar).
 */
function AnonymizeCard({ client, onDone }: { client: Client; onDone: () => Promise<unknown> }) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const anonymize = useMutation({
    mutationFn: () => clientsApi(workshopId).anonymize(client),
    onSettled: onDone,
  });
  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle>{t("clients.anonymize")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-muted-foreground text-sm">{t("clients.anonymizeHint")}</p>
        {anonymize.isError && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, anonymize.error)}
          </p>
        )}
        {open ? (
          <form
            className="grid gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              anonymize.mutate();
            }}
          >
            <Label htmlFor="anonymize-confirm">{t("clients.anonymizeConfirm", { name: client.name })}</Label>
            <Input
              id="anonymize-confirm"
              autoComplete="off"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                type="submit"
                variant="destructive"
                size="sm"
                disabled={anonymize.isPending || typed.trim() !== client.name.trim()}
              >
                {t("clients.anonymizeNow")}
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
                {t("common.cancel")}
              </Button>
            </div>
          </form>
        ) : (
          <div>
            <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
              {t("clients.anonymize")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
