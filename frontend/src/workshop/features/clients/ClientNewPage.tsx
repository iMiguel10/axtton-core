import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { Card, CardContent } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

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
      navigate(`/clients/${id}`);
    },
  });

  return (
    <section className="grid gap-4">
      <Link to="/clients" className="text-muted-foreground text-sm hover:underline">
        ← {t("clients.backToList")}
      </Link>
      <h1 className="text-2xl font-semibold">{t("clients.new")}</h1>
      <Card>
        <CardContent className="grid gap-3">
          <ClientForm
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
