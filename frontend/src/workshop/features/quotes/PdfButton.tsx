import { PdfButton as SharedPdfButton } from "@/shared/components/PdfButton";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { quotesApi } from "./api";

/** El PDF de una versión en otra pestaña (RF-37), con el taller activo. */
export function PdfButton({
  quoteId,
  label,
  disabled = false,
}: {
  quoteId: string;
  label: string;
  disabled?: boolean;
}) {
  const { workshopId } = useActiveWorkshop();
  return <SharedPdfButton load={() => quotesApi(workshopId).pdf(quoteId)} label={label} disabled={disabled} />;
}
