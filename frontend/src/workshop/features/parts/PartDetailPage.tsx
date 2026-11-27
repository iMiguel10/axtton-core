import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { ConfirmButton } from "@/shared/components/ConfirmButton";
import { DetailSkeleton } from "@/shared/components/Loading";
import { notify } from "@/shared/components/Toaster";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";
import { formatEur, formatPercentBp } from "@/shared/money";
import { formatQuantity } from "@/shared/quantity";

import { usePageCrumb } from "../layout/PageCrumb";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { partsApi, type Part, type PartInput } from "./api";
import { PartForm } from "./PartForm";
import { StockCard } from "./StockCard";

/** Ficha de una pieza del catálogo (RF-90): editable para el administrador, de
 * solo lectura para el mecánico (especificación §3). */
export function PartDetailPage() {
  const { t } = useTranslation();
  const { partId = "" } = useParams();
  const { workshopId, canManageParts } = useActiveWorkshop();
  const api = partsApi(workshopId);
  const queryClient = useQueryClient();
  const queryKey = ["part", workshopId, partId];
  const part = useQuery({ queryKey, queryFn: () => api.get(partId) });

  // Haya ido bien o no (un 409 si otra persona guardó antes), se vuelve a pedir
  // la ficha: así el formulario tiene la versión al día y lo último guardado.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ["parts", workshopId] }),
    ]);
  const save = useMutation({
    mutationFn: ({ current, input }: { current: Part; input: PartInput }) =>
      api.update(current, input),
    onSuccess: () => notify(t("parts.saved")),
    onSettled: refresh,
  });
  const archive = useMutation({
    mutationFn: (current: Part) => api.setArchived(current, current.archived_at === null),
    onSettled: refresh,
  });

  usePageCrumb(part.data ? part.data.description : null);
  if (part.isPending) return <DetailSkeleton />;
  if (part.isError) return <p role="alert">{errorMessage(t, part.error)}</p>;
  const current = part.data;
  const failed = save.error ?? archive.error;

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-semibold">{current.description}</h1>
        <span className="text-muted-foreground font-mono text-sm">{current.reference}</span>
        {current.archived_at && <Badge variant="secondary">{t("parts.archived")}</Badge>}
        {canManageParts &&
          (current.archived_at ? (
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              disabled={archive.isPending}
              onClick={() => archive.mutate(current)}
            >
              {t("parts.unarchive")}
            </Button>
          ) : (
            <ConfirmButton
              variant="outline"
              size="sm"
              className="ml-auto"
              disabled={archive.isPending}
              title={t("parts.archive")}
              description={t("parts.confirmArchive", { name: current.description })}
              confirmLabel={t("parts.archive")}
              onConfirm={() => archive.mutate(current)}
            >
              {t("parts.archive")}
            </ConfirmButton>
          ))}
      </div>
      {failed && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(t, failed)}
        </p>
      )}
      <Card>
        <CardContent>
          {canManageParts && !current.archived_at ? (
            <PartForm
              // Con otra versión, el formulario vuelve a empezar desde lo guardado.
              key={current.version}
              part={current}
              submitLabel={t("common.save")}
              pending={save.isPending}
              onSubmit={(input) => save.mutate({ current, input })}
            />
          ) : (
            <PartSummary part={current} />
          )}
        </CardContent>
      </Card>
      {current.tracks_stock && <StockCard part={current} />}
    </section>
  );
}

function PartSummary({ part }: { part: Part }) {
  const { t } = useTranslation();
  const { canViewCosts, canManageParts } = useActiveWorkshop();
  const rows: [string, string | null][] = [
    [t("parts.reference"), part.reference],
    [t("parts.brandShort"), part.brand],
    [
      t("parts.salePriceShort"),
      part.sale_price_cents === null ? t("parts.pricesHidden") : formatEur(part.sale_price_cents),
    ],
    ...(canViewCosts
      ? ([
          [
            t("parts.costPriceShort"),
            part.cost_price_cents === null ? null : formatEur(part.cost_price_cents),
          ],
        ] as [string, string | null][])
      : []),
    [t("parts.vat"), formatPercentBp(part.vat_bp)],
    [t("parts.condition"), t(`parts.conditions.${part.part_condition}`)],
    [
      t("parts.warranty"),
      part.warranty_months === null ? null : t("parts.warrantyMonths", { count: part.warranty_months }),
    ],
    [
      t("parts.tracksStock"),
      part.tracks_stock
        ? part.min_stock === null
          ? t("common.yes")
          : `${t("common.yes")} · ${t("parts.minStock")}: ${formatQuantity(part.min_stock)}`
        : t("parts.noStock"),
    ],
  ];
  return (
    <div className="grid gap-3">
      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[max-content_1fr]">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground text-sm">{label}</dt>
            <dd>{value || "—"}</dd>
          </div>
        ))}
      </dl>
      {!canManageParts && <p className="text-muted-foreground text-xs">{t("parts.readOnly")}</p>}
    </div>
  );
}
