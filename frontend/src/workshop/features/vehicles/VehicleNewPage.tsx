import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";

import { notify } from "@/shared/components/Toaster";
import { Card, CardContent } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

import { clientsApi } from "../clients/api";
import { ClientPicker, type PickedClient } from "../clients/ClientPicker";
import { usePageCrumb } from "../layout/PageCrumb";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { vehiclesApi, type VehicleInput } from "./api";
import { VehicleForm } from "./VehicleForm";

/**
 * Alta de un vehículo (RF-11). Nace con su titular (RF-12): sin elegirlo no se
 * puede guardar. Desde la ficha de un cliente llega con `?owner=<id>`.
 */
export function VehicleNewPage() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const ownerParam = params.get("owner");
  const preset = useQuery({
    queryKey: ["client", workshopId, ownerParam],
    queryFn: () => clientsApi(workshopId).get(ownerParam!),
    enabled: ownerParam !== null,
  });
  const [picked, setPicked] = useState<PickedClient | null | undefined>(undefined);
  // Hasta que se elija otro, el titular es el de la URL.
  const owner =
    picked !== undefined ? picked : preset.data ? { id: preset.data.id, name: preset.data.name } : null;

  const create = useMutation({
    mutationFn: ({ input, ownerId }: { input: VehicleInput; ownerId: string }) =>
      vehiclesApi(workshopId).create(input, ownerId),
    onSuccess: async ({ id }) => {
      await queryClient.invalidateQueries({ queryKey: ["vehicles", workshopId] });
      notify(t("vehicles.created"));
      navigate(`/vehicles/${id}`);
    },
  });

  usePageCrumb(t("vehicles.new"), true);
  return (
    <section className="grid gap-4">
      <Card>
        <CardContent className="grid gap-3">
          <VehicleForm
            // Desde la búsqueda del mostrador sin resultados: ?plate=.
            prefillPlate={params.get("plate") ?? undefined}
            before={
              <ClientPicker
                id="vehicle-owner"
                label={t("vehicles.owner")}
                value={owner}
                onChange={setPicked}
              />
            }
            submitLabel={t("vehicles.create")}
            pending={create.isPending}
            canSubmit={owner !== null}
            onSubmit={(input) => owner && create.mutate({ input, ownerId: owner.id })}
          />
          {owner === null && (
            <p className="text-muted-foreground text-sm">{t("vehicles.ownerRequired")}</p>
          )}
          {create.isError && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(t, create.error)}
            </p>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
