import type { ComponentProps, MouseEvent } from "react";
import { useNavigate } from "react-router-dom";

import { TableRow } from "@/shared/components/ui/table";
import { cn } from "@/shared/lib/utils";

// Lo que tiene su propia acción dentro de la fila: no se lo quita el clic de la fila.
const INTERACTIVE = "a, button, input, select, textarea, label, [role=button]";

/**
 * Una fila que lleva a su ficha al pulsarla en cualquier parte, no solo en el
 * primer campo. El enlace de ese campo se queda: es lo que usan el teclado y los
 * lectores de pantalla (una fila no es un control), y lo que da "abrir en otra
 * pestaña" con el botón derecho.
 *
 * No navega si el clic fue en un enlace o botón de dentro (el titular de un
 * vehículo lleva a su cliente) ni si se estaba seleccionando texto para copiarlo.
 * Con Ctrl o Cmd, abre en otra pestaña, como un enlace.
 */
export function LinkRow({ to, className, ...props }: ComponentProps<typeof TableRow> & { to: string }) {
  const navigate = useNavigate();
  function open(event: MouseEvent<HTMLTableRowElement>) {
    if ((event.target as HTMLElement).closest(INTERACTIVE)) return;
    if (window.getSelection()?.toString()) return;
    if (event.metaKey || event.ctrlKey) {
      window.open(to, "_blank", "noopener");
      return;
    }
    navigate(to);
  }
  return <TableRow className={cn("cursor-pointer", className)} onClick={open} {...props} />;
}
