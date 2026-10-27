import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Select } from "@/shared/components/form/Select";
import { Card, CardContent } from "@/shared/components/ui/card";
import { Label } from "@/shared/components/ui/label";
import { errorMessage } from "@/shared/lib/errors";

import { clientName } from "../clients/clientName";
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
    onSuccess: async ({ id }) => {
      await queryClient.invalidateQueries({ queryKey: ["orders", workshopId] });
      navigate(`/orders/${id}`);
    },
  });

  return (
    <section className="grid gap-4">
      <Link to="/orders" className="text-muted-foreground text-sm hover:underline">
        ← {t("orders.backToList")}
      </Link>
      <h1 className="text-2xl font-semibold">{t("orders.new")}</h1>
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
