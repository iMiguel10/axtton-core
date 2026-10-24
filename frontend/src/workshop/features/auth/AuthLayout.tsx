import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Brand } from "@/shared/components/Brand";
import { LanguageSwitcher, ThemeToggle } from "@/shared/components/Preferences";

/** Pantallas de acceso: panel de marca (oscuro en los dos temas) y el formulario. */
export function AuthLayout({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="grid min-h-svh md:grid-cols-2">
      <aside className="bg-brand text-brand-foreground hidden flex-col justify-between p-10 md:flex">
        <Brand className="text-xl" />
        <p className="max-w-sm text-sm opacity-80">{t("auth.tagline")}</p>
      </aside>
      <main className="flex flex-col p-6">
        <div className="flex justify-between md:justify-end">
          <Brand className="md:hidden" />
          <div className="flex gap-1">
            <LanguageSwitcher />
            <ThemeToggle />
          </div>
        </div>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-6">
          <h1 className="text-2xl font-semibold">{title}</h1>
          {children}
        </div>
      </main>
    </div>
  );
}
