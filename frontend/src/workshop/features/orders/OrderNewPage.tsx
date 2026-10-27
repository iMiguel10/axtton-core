import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";

import { notify } from "@/shared/components/Toaster";
import { Select } from "@/shared/components/form/Select";
import { Card, CardContent } from "@/shared/components/ui/card";
import { Label } from "@/shared/components/ui/label";
import { errorMessage } from "@/shared/lib/errors";

import { clientName } from "../clients/clientName";
import { usePageCrumb } from "../layout/PageCrumb";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { vehiclesApi, type Vehicle } from "../vehicles/api";
import { VehiclePicker } from "../vehicles/VehiclePicker";
import { ordersApi, TYPES, type OrderType, type ReceptionInput } from "./api";
import { ReceptionForm } from "./ReceptionForm";

/**
 * Abrir una orden (RF-20): se elige el vehículo y su titular es el cliente, sin
 * elegirlo aparte. Desde la ficha de un vehículo llega con `?vehicle=<id>`.
 * Abrirla para un cliente y vehículo ya registrados lleva menos de un minuto
 * (RNF-21): matrícula, tipo y abrir; el resto es opcional.
 */
export function OrderNewPage() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const vehicleParam = useSearchParams()[0].get("vehicle");
  const preset = useQuery({
    queryKey: ["vehicle", workshopId, vehicleParam],
    queryFn: () => vehiclesApi(workshopId).get(vehicleParam!),
    enabled: vehicleParam !== null,
  });
  const [picked, setPicked] = useState<Vehicle | null | undefined>(undefined);
  const vehicle = picked !== undefined ? picked : (preset.data ?? null);
  const [type, setType] = useState<OrderType>("breakdown");

  const open = useMutation({
    mutationFn: ({ vehicleId, input }: { vehicleId: string; input: ReceptionInput }) =>
      ordersApi(workshopId).open(vehicleId, type, input),
    onSuccess: async ({ id, code }) => {
      await queryClient.invalidateQueries({ queryKey: ["orders", workshopId] });
      notify(t("orders.opened", { code }));
      navigate(`/orders/${id}`);
    },
  });

  usePageCrumb(t("orders.new"), true);
  return (
    <section className="grid gap-4">
      <Card>
        <CardContent className="grid gap-3">
          <ReceptionForm
            before={
              <>
                <VehiclePicker
                  id="order-vehicle"
                  label={t("orders.vehicle")}
                  value={vehicle}
                  onChange={setPicked}
                />
                <div className="grid gap-1.5">
                  <Label htmlFor="order-type">{t("orders.type")}</Label>
                  <Select
                    id="order-type"
                    value={type}
                    onChange={(event) => setType(event.target.value as OrderType)}
                  >
                    {TYPES.map((value) => (
                      <option key={value} value={value}>
                        {t(`orders.types.${value}`)}
                      </option>
                    ))}
                  </Select>
                </div>
                {vehicle && (
                  <p className="text-sm md:col-span-2">
                    {t("orders.clientWillBe", { name: vehicle.owner ? clientName(t, vehicle.owner.name) : "—" })}
                  </p>
                )}
              </>
            }
            submitLabel={t("orders.open")}
            pending={open.isPending}
            canSubmit={vehicle !== null}
            onSubmit={(input) => vehicle && open.mutate({ vehicleId: vehicle.id, input })}
          />
          {open.isError && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(t, open.error)}
            </p>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
