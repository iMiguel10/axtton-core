import { Languages, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/shared/components/ui/button";

const THEME_KEY = "theme";

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    // Navegación privada o almacenamiento bloqueado: se sigue sin recordar.
    return null;
  }
}

/** Aplica el tema guardado, o el del sistema. Se llama antes de pintar nada. */
export function applyInitialTheme(): void {
  const stored = readStorage(THEME_KEY);
  const dark =
    stored === "dark" ||
    (stored === null && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function ThemeToggle() {
  const { t } = useTranslation();
  const [dark, setDark] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );
  function toggle() {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem(THEME_KEY, next ? "dark" : "light");
    } catch {
      /* sin almacenamiento: el cambio dura hasta recargar */
    }
    setDark(next);
  }
  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label={t("common.toggleTheme")}>
      {dark ? <Sun /> : <Moon />}
    </Button>
  );
}

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const next = i18n.resolvedLanguage === "es" ? "en" : "es";
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => void i18n.changeLanguage(next)}
      aria-label={t("common.changeLanguage")}
    >
      <Languages />
      {next.toUpperCase()}
    </Button>
  );
}
