import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { clientsApi, type Client, type ClientInput } from "./api";
import { ClientForm } from "./ClientForm";

/** Ficha de un cliente (RF-10): editable para quien gestiona clientes, de solo
 * lectura para el mecánico (especificación §3). */
export function ClientDetailPage() {
  const { t } = useTranslation();
  const { clientId = "" } = useParams();
  const { workshopId, canManageClients } = useActiveWorkshop();
  const api = clientsApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["client", workshopId, clientId];
  const client = useQuery({ queryKey, queryFn: () => api.get(clientId) });
  const [saved, setSaved] = useState(false);

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
    onMutate: () => setSaved(false),
    onSuccess: () => setSaved(true),
    onSettled: refresh,
  });
  const archive = useMutation({
    mutationFn: (current: Client) => api.setArchived(current, current.archived_at === null),
    onMutate: () => setSaved(false),
    onSettled: refresh,
  });

  if (client.isPending) return <p>{t("common.loading")}</p>;
  if (client.isError) return <p role="alert">{errorMessage(t, client.error)}</p>;
  const current = client.data;
  const failed = save.error ?? archive.error;

  return (
    <section className="grid gap-4">
      <Link to="/clients" className="text-muted-foreground text-sm hover:underline">
        ← {t("clients.backToList")}
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-semibold">{current.name}</h1>
        {current.archived_at && <Badge variant="secondary">{t("clients.archived")}</Badge>}
        {canManageClients && (
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            disabled={archive.isPending}
            onClick={() => {
              const archiving = current.archived_at === null;
              if (!archiving || window.confirm(t("clients.confirmArchive", { name: current.name }))) {
                archive.mutate(current);
              }
            }}
          >
            {t(current.archived_at ? "clients.unarchive" : "clients.archive")}
          </Button>
        )}
      </div>
      {failed && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, failed)}
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm">
          {t("clients.saved")}
        </p>
      )}
      <Card>
        <CardContent>
          {canManageClients ? (
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
    </section>
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
          <dd className="whitespace-pre-line">{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
