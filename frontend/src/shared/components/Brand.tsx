import { cn } from "@/shared/lib/utils";

/**
 * Logotipo en texto: AXTTON en el color del texto, CORE en dorado (guía de marca).
 * El dorado sobre fondo claro no llega a 4.5:1, pero WCAG exime de contraste el
 * texto que forma parte de un logotipo; en ningún otro texto se usa ese dorado.
 */
export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn("font-semibold tracking-[0.2em] whitespace-nowrap", className)}>
      AXTTON <span className="text-brand-accent">CORE</span>
    </span>
  );
}
