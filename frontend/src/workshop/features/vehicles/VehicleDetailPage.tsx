import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { DetailSkeleton } from "@/shared/components/Loading";
import { Badge } from "@/shared/components/ui/badge";
import { Button, buttonVariants } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/components/ui/table";
import { notify } from "@/shared/components/Toaster";
import { errorMessage } from "@/shared/lib/errors";
import { useDates } from "@/shared/lib/dates";

import { clientName } from "../clients/clientName";
import { ClientPicker, type PickedClient } from "../clients/ClientPicker";
import { RelatedOrders } from "../orders/OrderBits";
import { usePageCrumb } from "../layout/PageCrumb";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { vehiclesApi, type VehicleDetail, type VehicleInput } from "./api";
import { VehicleForm } from "./VehicleForm";

/**
 * Ficha de un vehículo (RF-11, RF-13): sus datos, su titular actual y todos sus
 * periodos de titularidad, y todas sus órdenes.
 */
export function VehicleDetailPage() {
  const { t } = useTranslation();
  const { vehicleId = "" } = useParams();
  const { workshopId, canManageClients, canManageOrders } = useActiveWorkshop();
  const api = vehiclesApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["vehicle", workshopId, vehicleId];
  const vehicle = useQuery({ queryKey, queryFn: () => api.get(vehicleId) });

  // Haya ido bien o no (un 409), se vuelve a pedir: versión y titular al día.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ["vehicles", workshopId] }),
    ]);
  const save = useMutation({
    mutationFn: ({ current, input }: { current: VehicleDetail; input: VehicleInput }) =>
      api.update(current, input),
    onSuccess: () => notify(t("vehicles.saved")),
    onSettled: refresh,
  });
  const transfer = useMutation({
    mutationFn: ({ current, to }: { current: VehicleDetail; to: PickedClient }) =>
      api.changeOwner(current, to.id),
    onSuccess: (_, { to }) => notify(t("vehicles.ownerChanged", { name: to.name })),
    onSettled: refresh,
  });

  usePageCrumb(vehicle.data?.plate);
  if (vehicle.isPending) return <DetailSkeleton />;
  if (vehicle.isError) return <p role="alert">{errorMessage(t, vehicle.error)}</p>;
  const current = vehicle.data;
  const failed = save.error ?? transfer.error;

  return (
    <section className="grid gap-4">
      <div>
        <h1 className="tabular-nums text-2xl font-semibold">{current.plate}</h1>
        <p className="text-muted-foreground">
          {[current.make, current.model, current.year].filter(Boolean).join(" · ") || "—"}
        </p>
      </div>
      {failed && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, failed)}
        </p>
      )}
      <OwnerCard
        // Al cambiar la versión, el selector vuelve a cerrarse.
        key={`owner-${current.version}`}
        vehicle={current}
        canChange={canManageClients}
        pending={transfer.isPending}
        onChange={(to) => transfer.mutate({ current, to })}
      />
      <Card>
        <CardHeader>
          <CardTitle>{t("vehicles.data")}</CardTitle>
        </CardHeader>
        <CardContent>
          {canManageClients ? (
            <VehicleForm
              key={current.version}
              vehicle={current}
              submitLabel={t("common.save")}
              pending={save.isPending}
              onSubmit={(input) => save.mutate({ current, input })}
            />
          ) : (
            <VehicleSummary vehicle={current} />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{t("vehicles.orders")}</CardTitle>
          {canManageOrders && (
            <Link
              to={`/orders/new?vehicle=${current.id}`}
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              {t("orders.new")}
            </Link>
          )}
        </CardHeader>
        <CardContent>
          {/* Todas sus órdenes, de todos sus titulares (RF-13). */}
          <RelatedOrders filters={{ vehicleId: current.id }} show={{ client: true }} />
        </CardContent>
      </Card>
    </section>
  );
}

function OwnerCard({
  vehicle,
  canChange,
  pending,
  onChange,
}: {
  vehicle: VehicleDetail;
  canChange: boolean;
  pending: boolean;
  onChange: (to: PickedClient) => void;
}) {
  const { t } = useTranslation();
  const dates = useDates();
  const [changing, setChanging] = useState(false);
  const [to, setTo] = useState<PickedClient | null>(null);
  const date = (iso: string) => dates.date(iso);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("vehicles.owner")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/clients/${vehicle.owner.id}`} className="link">
            {clientName(t, vehicle.owner.name)}
          </Link>
          {canChange && !changing && (
            <Button variant="outline" size="sm" className="ml-auto" onClick={() => setChanging(true)}>
              {t("vehicles.changeOwner")}
            </Button>
          )}
        </div>
        {changing && (
          <div className="grid gap-2 rounded-lg border p-3">
            <ClientPicker
              id="vehicle-new-owner"
              label={t("vehicles.newOwner")}
              value={to}
              onChange={setTo}
              exclude={vehicle.owner.id}
            />
            <p className="text-muted-foreground text-xs">{t("vehicles.changeOwnerHint")}</p>
            <div className="flex gap-2">
              <Button size="sm" disabled={to === null || pending} onClick={() => to && onChange(to)}>
                {t("vehicles.confirmOwner")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setChanging(false)}>
                {t("common.cancel")}
              </Button>
            </div>
          </div>
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("vehicles.ownerName")}</TableHead>
              <TableHead>{t("vehicles.since")}</TableHead>
              <TableHead>{t("vehicles.until")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {vehicle.ownerships.map((period) => (
              <TableRow key={period.started_at}>
                <TableCell>{clientName(t, period.client.name)}</TableCell>
                <TableCell>{date(period.started_at)}</TableCell>
                <TableCell>
                  {period.ended_at ? (
                    date(period.ended_at)
                  ) : (
                    <Badge variant="success">{t("vehicles.currentOwner")}</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function VehicleSummary({ vehicle }: { vehicle: VehicleDetail }) {
  const { t, i18n } = useTranslation();
  const dates = useDates();
  const date = (iso: string | null) =>
    dates.day(iso);
  const rows: [string, string | null][] = [
    [t("vehicles.vin"), vehicle.vin],
    [t("vehicles.fuel"), vehicle.fuel && t(`vehicles.fuels.${vehicle.fuel}`)],
    [t("vehicles.nextItv"), date(vehicle.next_itv_date)],
    [t("vehicles.nextServiceDate"), date(vehicle.next_service_date)],
    [
      t("vehicles.nextServiceKm"),
      vehicle.next_service_km?.toLocaleString(i18n.language) ?? null,
    ],
  ];
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[max-content_1fr]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground text-sm">{label}</dt>
          <dd>{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
