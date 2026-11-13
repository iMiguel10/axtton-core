import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button } from "@/shared/components/ui/button";
import { errorMessage } from "@/shared/lib/errors";

import { takeNextPath } from "../../lib/nextOrder";
import { demoEnter, fetchDemoClients } from "./api";

/**
 * Solo en la demo (F4 paso 8): la demo desplegada no tiene correo, así que se
 * entra como uno de sus clientes con un botón. Fuera de la demo la API responde
 * 404 y aquí no se enseña nada.
 */
export function DemoEntry({ workshopId }: { workshopId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const clients = useQuery({
    queryKey: ["portal", "demo-clients", workshopId],
    queryFn: () => fetchDemoClients(workshopId),
    retry: false,
  });
  const enter = useMutation({
    mutationFn: (email: string) => demoEnter(workshopId, email),
    onSuccess: () => navigate(takeNextPath(workshopId), { replace: true }),
  });

  if (!clients.data?.length) return null;
  return (
    <section className="grid gap-3 rounded-lg border border-dashed p-4" aria-labelledby="demo-entry">
      <div className="grid gap-1">
        <h2 id="demo-entry" className="text-sm font-medium">
          {t("portal.demo.title")}
        </h2>
        <p className="text-muted-foreground text-xs">{t("portal.demo.description")}</p>
      </div>
      <div className="grid gap-2">
        {clients.data.map((client) => (
          <Button
            key={client.email}
            variant="outline"
            disabled={enter.isPending}
            onClick={() => enter.mutate(client.email)}
          >
            {t("portal.demo.enterAs", { name: client.name })}
          </Button>
        ))}
      </div>
      {enter.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, enter.error)}
        </p>
      )}
    </section>
  );
}
