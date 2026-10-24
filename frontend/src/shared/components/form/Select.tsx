import type { ComponentProps } from "react";

import { cn } from "@/shared/lib/utils";

/**
 * <select> nativo con el aspecto de Input. Nativo a propósito: teclado, lector de
 * pantalla y móvil funcionan sin nada más.
 */
export function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "border-input bg-background focus-visible:border-ring focus-visible:ring-ring/50 h-8 rounded-lg border px-2 text-sm outline-none focus-visible:ring-[3px] disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
