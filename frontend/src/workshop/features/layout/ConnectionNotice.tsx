import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useOnline } from "@/shared/lib/useOnline";

import { onDraftsChanged, pendingDrafts, type Draft } from "../../lib/drafts";
import { useActiveWorkshop } from "../session/ActiveWorkshop";

/**
 * Bajo la cabecera, en cualquier pantalla (RNF-22): si no hay conexión, y qué
 * se ha quedado sin enviar, con el enlace a su orden. Al abrirla, se envía.
 */
export function ConnectionNotice() {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const online = useOnline();
  const [pending, setPending] = useState<Draft<unknown>[]>([]);

  useEffect(() => {
    let ignore = false;
    const load = () =>
      void pendingDrafts(workshopId).then((drafts) => {
        if (!ignore) setPending(drafts);
      });
    load();
    const unsubscribe = onDraftsChanged(load);
    return () => {
      ignore = true;
      unsubscribe();
    };
  }, [workshopId]);

  if (online && pending.length === 0) return null;
  return (
    <div role="status" className="bg-muted border-b">
      <div className="mx-auto grid max-w-6xl gap-1 px-4 py-2 text-sm">
        {!online && <p className="font-medium">{t("drafts.offline")}</p>}
        {pending.length > 0 && (
          <p>
            {t("drafts.pendingList")}{" "}
            {pending.map((draft, index) => (
              <span key={draft.key}>
                {index > 0 && ", "}
                <Link to={`/orders/${draft.orderId}`} className="underline">
                  {t(`drafts.kinds.${draft.kind}`, { code: draft.orderCode })}
                </Link>
              </span>
            ))}
          </p>
        )}
      </div>
    </div>
  );
}
