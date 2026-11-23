import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { notify } from "@/shared/components/Toaster";
import { Card, CardContent } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

import { usePageCrumb } from "../layout/PageCrumb";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { partsApi, type PartInput } from "./api";
import { PartForm } from "./PartForm";

/** Alta de una pieza en el catálogo (RF-90). Al guardarla, se abre su ficha. */
export function PartNewPage() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = partsApi(workshopId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: (input: PartInput) => api.create(input),
    onSuccess: async ({ id }) => {
      await queryClient.invalidateQueries({ queryKey: ["parts", workshopId] });
      notify(t("parts.created"));
      navigate(`/parts/${id}`);
    },
  });

  usePageCrumb(t("parts.new"), true);
  return (
    <section className="grid gap-4">
      <Card>
        <CardContent className="grid gap-3">
          <PartForm
            submitLabel={t("parts.create")}
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
