import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/shared/components/ui/button";
import { isOutdated, useServerMeta } from "@/shared/lib/version";

/**
 * Bajo la cabecera, para cualquier actor: tras un despliegue, la API ya es la
 * nueva y esta pestaña sigue con la interfaz vieja. Recargar la trae; no se hace
 * solo, que podría haber un formulario a medias (los borradores se guardan, pero
 * no todo es un borrador).
 */
export function NewVersionNotice() {
  const { t } = useTranslation();
  const meta = useServerMeta();
  if (!isOutdated(meta.data)) return null;
  return (
    <div role="status" className="bg-muted border-b">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
        <p className="font-medium">{t("version.newAvailable")}</p>
        <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
          <RefreshCw />
          {t("version.reload")}
        </Button>
      </div>
    </div>
  );
}
