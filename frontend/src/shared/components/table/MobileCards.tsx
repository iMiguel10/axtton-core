import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { cn } from "@/shared/lib/utils";

/**
 * En el móvil, una tabla no cabe: cada fila pasa a ser una tarjeta que se toca
 * entera (es un enlace). Se usa junto a la tabla: la tabla con `hidden md:table`
 * (o envuelta en `hidden md:block`) y esto, que solo se ve por debajo de `md`.
 */
export function MobileCards({ children }: { children: ReactNode }) {
  return <ul className="grid gap-2 md:hidden">{children}</ul>;
}

export function MobileCard({
  to,
  title,
  aside,
  lines,
  className,
}: {
  to: string;
  title: ReactNode;
  /** Lo de la derecha del título: el estado, una etiqueta. */
  aside?: ReactNode;
  /** Las líneas de debajo, en gris: vehículo, cliente, fechas. */
  lines: ReactNode[];
  className?: string;
}) {
  return (
    <li>
      <Link
        to={to}
        className={cn(
          "hover:bg-muted/50 active:bg-muted flex flex-col gap-1 rounded-lg border p-3 transition-colors",
          className,
        )}
      >
        <span className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-medium tabular-nums">{title}</span>
          {aside}
        </span>
        {lines.filter(Boolean).map((line, index) => (
          <span key={index} className="text-muted-foreground text-sm">
            {line}
          </span>
        ))}
      </Link>
    </li>
  );
}
