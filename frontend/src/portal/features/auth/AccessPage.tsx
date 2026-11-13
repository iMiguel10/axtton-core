import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { AuthLayout } from "@/shared/components/AuthLayout";
import { Button } from "@/shared/components/ui/button";
import { errorMessage } from "@/shared/lib/errors";

import { takeNextPath } from "../../lib/nextOrder";
import { consumeLink } from "./api";


/**
 * El enlace del email (RF-40). No entra solo al abrirse: pide pulsar un botón.
 * Algunos correos abren los enlaces para revisarlos antes que la persona, y si
 * entrar fuera automático, gastarían el enlace, que solo sirve una vez (RNF-04).
 */
export function AccessPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { workshopId = "" } = useParams();
  // El token va en el fragmento (`#…`), que el navegador nunca envía al servidor.
  // Se guarda en el estado y luego se quita de la barra de direcciones, para que
  // no quede en el historial. Leer y quitar van separados: en modo estricto, React
  // llama dos veces al inicializador, y la segunda ya no lo encontraría.
  const [token] = useState(() => window.location.hash.slice(1));
  useEffect(() => {
    if (window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  }, []);
  const enter = useMutation({
    mutationFn: () => consumeLink(workshopId, token),
    // A la orden del aviso que trajo hasta aquí, si la había (F5 paso 5).
    onSuccess: () => navigate(takeNextPath(workshopId), { replace: true }),
  });

  const requestAnother = (
    <Link to={`/login/${encodeURIComponent(workshopId)}`} className="link">
      {t("portal.access.requestAnother")}
    </Link>
  );

  return (
    <AuthLayout
      title={t("portal.access.title")}
      description={token ? t("portal.access.description") : undefined}
      tagline={t("portal.tagline")}
      footer={requestAnother}
    >
      {token ? (
        <div className="grid gap-4">
          {enter.isError && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(t, enter.error)}
            </p>
          )}
          <Button onClick={() => enter.mutate()} disabled={enter.isPending || enter.isError}>
            {t("portal.access.submit")}
          </Button>
        </div>
      ) : (
        <p role="alert">{t("portal.access.missing")}</p>
      )}
    </AuthLayout>
  );
}
