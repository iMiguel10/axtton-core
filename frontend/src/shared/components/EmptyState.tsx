import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/shared/lib/utils";

/**
 * Lo que se ve cuando una lista está vacía: un icono, qué pasa y, si hay algo que
 * hacer, el botón para hacerlo ("Aún no hay clientes" → "Nuevo cliente"). Una
 * frase gris suelta parecía un error o una pantalla a medio cargar.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  compact = false,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
  /** Dentro de una tarjeta pequeña (los trabajos de una orden): menos aire. */
  compact?: boolean;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-3 text-center", compact ? "py-4" : "py-10")}>
      <span className="bg-muted text-muted-foreground flex size-11 items-center justify-center rounded-full">
        <Icon className="size-5" />
      </span>
      <div className="grid gap-1">
        <p className="font-medium">{title}</p>
        {description && <p className="text-muted-foreground max-w-sm text-sm">{description}</p>}
      </div>
      {action}
    </div>
  );
}
