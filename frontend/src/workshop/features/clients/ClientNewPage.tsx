import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";

import { notify } from "@/shared/components/Toaster";
import { Card, CardContent } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

import { usePageCrumb } from "../layout/PageCrumb";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { clientsApi, type ClientInput } from "./api";
import { ClientForm } from "./ClientForm";

/** Alta de un cliente (RF-10). Al guardarlo, se abre su ficha. */
export function ClientNewPage() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = clientsApi(workshopId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: (input: ClientInput) => api.create(input),
    onSuccess: async ({ id }) => {
      await queryClient.invalidateQueries({ queryKey: ["clients", workshopId] });
      notify(t("clients.created"));
      navigate(`/clients/${id}`);
    },
  });

  const [params] = useSearchParams();
  usePageCrumb(t("clients.new"), true);
  return (
    <section className="grid gap-4">
      <Card>
        <CardContent className="grid gap-3">
          <ClientForm
            // Desde la búsqueda del mostrador sin resultados: ?name= o ?phone=.
            prefill={{
              name: params.get("name") ?? undefined,
              phone: params.get("phone") ?? undefined,
            }}
            submitLabel={t("clients.create")}
            pending={create.isPending}
            onSubmit={(input) => create.mutate(input)}
          />
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
