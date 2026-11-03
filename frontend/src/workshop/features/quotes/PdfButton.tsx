import { useMutation } from "@tanstack/react-query";
import { FileDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/shared/components/ui/button";
import { errorMessage } from "@/shared/lib/errors";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { quotesApi } from "./api";

/**
 * Abre el PDF de una versión en otra pestaña (RF-37). Lo genera la API al
 * pedirlo (A14). Va con `fetch` y no con un enlace, porque un enlace no puede
 * llevar la cabecera del taller activo.
 */
export function PdfButton({
  quoteId,
  label,
  disabled = false,
}: {
  quoteId: string;
  label: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const open = useMutation({
    mutationFn: async () => {
      // La pestaña se abre al pulsar: abierta después de esperar a la API, el
      // navegador la tomaría por una ventana emergente y la bloquearía.
      const tab = window.open("", "_blank");
      try {
        const url = URL.createObjectURL(await quotesApi(workshopId).pdf(quoteId));
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
