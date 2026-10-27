import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Brand } from "@/shared/components/Brand";
import { LanguageSwitcher, ThemeToggle } from "@/shared/components/Preferences";

/**
 * Pantallas de acceso, como el bloque login-02 de shadcn: el formulario a la
 * izquierda, con la marca arriba, y el panel de marca a la derecha (oscuro en los
 * dos temas; desde `lg`, en el móvil no cabe). Todas las de acceso la comparten:
 * entrar, aceptar una invitación, recuperar y cambiar la contraseña.
 */
export function AuthLayout({
  title,
  description,
  footer,
  children,
}: {
  title: string;
  description?: ReactNode;
  /** Bajo el formulario: el enlace a la otra pantalla de acceso. */
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex items-center justify-between gap-2">
          <Brand className="h-10" />
          <div className="flex gap-1">
            <LanguageSwitcher />
            <ThemeToggle />
          </div>
        </div>
        <main className="flex flex-1 items-center justify-center">
          <div className="flex w-full max-w-sm flex-col gap-6">
            <div className="flex flex-col items-center gap-2 text-center">
              <h1 className="text-2xl font-semibold">{title}</h1>
              {description && <p className="text-muted-foreground text-sm text-balance">{description}</p>}
            </div>
            {children}
            {footer && <div className="text-muted-foreground text-center text-sm">{footer}</div>}
          </div>
        </main>
      </div>
      <BrandPanel />
    </div>
  );
}

/**
 * La mitad de la marca. En CSS, sin imagen: cuando llegue el logotipo, va aquí
 * (y en la barra lateral).
 */
function BrandPanel() {
  const { t } = useTranslation();
  return (
    <aside className="bg-brand text-brand-foreground relative hidden overflow-hidden lg:flex lg:flex-col lg:justify-center lg:p-16">
      {/* Una retícula tenue y un resplandor dorado: textura, no contenido. */}
      <div
        aria-hidden
        className="absolute inset-0 opacity-[0.07] [background-image:linear-gradient(var(--brand-foreground)_1px,transparent_1px),linear-gradient(90deg,var(--brand-foreground)_1px,transparent_1px)] [background-size:48px_48px]"
      />
      <div
        aria-hidden
        className="absolute -right-32 -bottom-32 size-[28rem] rounded-full opacity-20 blur-3xl [background:radial-gradient(circle,var(--brand-accent),transparent_70%)]"
      />
      <div className="relative flex max-w-md flex-col gap-6">
        <Brand tone="onDark" className="h-20 self-start" />
        <span aria-hidden className="bg-brand-accent h-px w-16" />
        <p className="text-lg leading-relaxed opacity-90">{t("auth.tagline")}</p>
      </div>
    </aside>
  );
}
