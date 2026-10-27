import { useState } from "react";

import { useDates } from "@/shared/lib/dates";

/**
 * Un instante dicho como se dice en el taller ("hace 3 días", "mañana"), con el
 * exacto al pasar el ratón y en `dateTime` para los lectores de pantalla.
 */
export function When({ iso, className }: { iso: string; className?: string }) {
  const dates = useDates();
  // La hora de referencia, una vez por montaje: leer el reloj al pintar no es puro.
  const [now] = useState(() => Date.now());
  return (
    <time dateTime={iso} title={dates.long(iso)} className={className}>
      {dates.relative(iso, now)}
    </time>
  );
}
