import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { Brand } from "@/shared/components/Brand";
import { LanguageSwitcher, ThemeToggle } from "@/shared/components/Preferences";
import { Button } from "@/shared/components/ui/button";
import { cn } from "@/shared/lib/utils";

import { signOut } from "../../lib/session";
import { useActiveWorkshop } from "../session/ActiveWorkshop";

type NavItem = { to: string; label: string };

export function AppLayout({
  nav,
  workshopSwitcher = false,
  children,
}: {
  nav: NavItem[];
  /** Solo para el personal: el superadministrador no tiene taller activo. */
  workshopSwitcher?: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="min-h-svh">
      <header className="bg-brand text-brand-foreground">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Brand />
          {workshopSwitcher && <WorkshopSwitcher />}
          <nav aria-label={t("nav.main")} className="flex gap-1">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-sm hover:bg-white/10",
                    isActive && "bg-white/15 font-medium",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          {/* Los botones heredan los colores del panel oscuro en los dos temas. */}
          <div className="ml-auto flex gap-1 [&_button]:text-brand-foreground [&_button:hover]:bg-white/10">
            <LanguageSwitcher />
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={() => void signOut()}>
              {t("nav.signOut")}
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl p-4 md:p-6">{children}</main>
    </div>
  );
}

function WorkshopSwitcher() {
  const { t } = useTranslation();
  const { workshopId, workshopName, workshops, select } = useActiveWorkshop();
  if (workshops.length === 1) {
    return <span className="text-sm opacity-80">{workshopName}</span>;
  }
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="sr-only">{t("workshop.active")}</span>
      <select
        value={workshopId}
        onChange={(event) => select(event.target.value)}
        className="rounded-md border border-white/20 bg-transparent px-2 py-1 [&>option]:text-black"
      >
        {workshops.map((w) => (
          <option key={w.workshop_id} value={w.workshop_id}>
            {w.workshop_name}
          </option>
        ))}
      </select>
    </label>
  );
}
