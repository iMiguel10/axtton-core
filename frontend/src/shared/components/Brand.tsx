import logo from "@/shared/assets/brand/logo.png";
import logoLight from "@/shared/assets/brand/logo-light.png";
import mark from "@/shared/assets/brand/mark.png";
import markLight from "@/shared/assets/brand/mark-light.png";
import { cn } from "@/shared/lib/utils";

/**
 * El logotipo de AXTTON CORE (guía de marca): el símbolo, AXTTON en negro y CORE
 * en dorado. Las variantes claras (`-light`) cambian el negro por marfil y dejan
 * el dorado: son para fondos oscuros. WCAG exime de contraste a un logotipo.
 *
 * `tone`: "auto" sigue el tema (la oscura en claro, la clara en oscuro);
 * "onDark", para lo que es oscuro en los dos temas (la barra lateral, el panel de
 * acceso). El tamaño se da con la altura (`className="h-8"`).
 */
export function Brand({
  tone = "auto",
  className,
}: {
  tone?: "auto" | "onDark";
  className?: string;
}) {
  return <Logo dark={logo} light={logoLight} tone={tone} className={cn("h-8", className)} />;
}

/** Solo el símbolo: la barra lateral plegada. */
export function BrandMark({
  tone = "auto",
  className,
}: {
  tone?: "auto" | "onDark";
  className?: string;
}) {
  return <Logo dark={mark} light={markLight} tone={tone} className={cn("h-6", className)} />;
}

function Logo({
  dark,
  light,
  tone,
  className,
}: {
  dark: string;
  light: string;
  tone: "auto" | "onDark";
  className: string;
}) {
  if (tone === "onDark") {
    return <img src={light} alt="AXTTON CORE" className={cn("w-auto shrink-0", className)} />;
  }
  return (
    <>
      <img src={dark} alt="AXTTON CORE" className={cn("w-auto shrink-0 dark:hidden", className)} />
      <img src={light} alt="AXTTON CORE" className={cn("hidden w-auto shrink-0 dark:block", className)} />
    </>
  );
}
