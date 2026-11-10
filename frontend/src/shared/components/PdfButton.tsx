import { useMutation } from "@tanstack/react-query";
import { FileDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/shared/components/ui/button";
import { errorMessage } from "@/shared/lib/errors";

/**
 * Abre un PDF que genera la API al pedirlo (A14) en otra pestaña. Va con `fetch`
 * y no con un enlace: el SDK de la sesión renueva el token si ha caducado, y el
 * taller necesita además la cabecera del taller activo. Lo usan el taller (RF-37)
 * y el portal (RF-54), cada uno con su `load`.
 */
export function PdfButton({
  load,
  label,
  disabled = false,
}: {
  load: () => Promise<Blob>;
  label: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const open = useMutation({
    mutationFn: async () => {
      // La pestaña se abre al pulsar: abierta después de esperar a la API, el
      // navegador la tomaría por una ventana emergente y la bloquearía.
      const tab = window.open("", "_blank");
      try {
        const url = URL.createObjectURL(await load());
        if (tab) {
          tab.location.href = url;
        } else {
          // Bloqueada de todos modos: se descarga.
          const link = document.createElement("a");
          link.href = url;
          link.download = "presupuesto.pdf";
          link.click();
        }
        // La pestaña ya lo cargó: se libera la memoria del navegador.
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      } catch (error) {
        tab?.close();
        throw error;
      }
    },
  });
  return (
    <>
      <Button variant="outline" size="sm" disabled={disabled || open.isPending} onClick={() => open.mutate()}>
        <FileDown aria-hidden />
        {label}
      </Button>
      {open.isError && (
        <p role="alert" className="text-destructive basis-full text-sm">
          {errorMessage(t, open.error)}
        </p>
      )}
    </>
  );
}
