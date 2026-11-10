import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Outlet } from "react-router-dom";
import Session from "supertokens-web-js/recipe/session";

import { Brand } from "@/shared/components/Brand";
import { AppSplash } from "@/shared/components/Loading";
import { LanguageSwitcher, ThemeToggle } from "@/shared/components/Preferences";
import { Button } from "@/shared/components/ui/button";
import { ApiError } from "@/shared/lib/apiClient";
import { TimeZoneProvider } from "@/shared/lib/dates";
import { errorMessage } from "@/shared/lib/errors";

import { loginPath, rememberWorkshop } from "../../lib/lastWorkshop";
import { fetchMe } from "../auth/api";

export function usePortalMe() {
  return useQuery({ queryKey: ["portal", "me"], queryFn: fetchMe });
}

/** Al salir, a la entrada del mismo taller: es por donde se vuelve a entrar. */
async function signOut(): Promise<void> {
  await Session.signOut();
  window.location.assign(loginPath());
}

/** La cabecera del portal y, debajo, sus pantallas, con las fechas en la zona del taller. */
export function PortalLayout() {
  const { t } = useTranslation();
  const me = usePortalMe();
  const workshopId = me.data?.workshop_id;

  useEffect(() => {
    if (workshopId) rememberWorkshop(workshopId);
  }, [workshopId]);

  if (me.isPending) return <AppSplash />;

  return (
    <div className="mx-auto flex min-h-svh max-w-2xl flex-col gap-6 p-4 sm:p-6">
      <header className="flex items-center justify-between gap-2">
        <Brand className="h-8" />
        <div className="flex items-center gap-1">
          <LanguageSwitcher />
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={() => void signOut()}>
            {t("portal.home.signOut")}
          </Button>
        </div>
      </header>
      <main className="grid gap-6">
        {me.isError ? (
          <NoAccess error={me.error} />
        ) : (
          <TimeZoneProvider timeZone={me.data.timezone}>
            <Outlet />
          </TimeZoneProvider>
        )}
      </main>
    </div>
  );
}

/** La sesión existe pero no da acceso: es del personal, o el taller la cortó. */
function NoAccess({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (error instanceof ApiError && error.code === "wrong_actor") {
    return (
      <div className="grid gap-3">
        <p role="alert">{t("portal.home.staffSession")}</p>
        <a href="/" className="link">
          {t("portal.home.goToWorkshop")}
        </a>
      </div>
    );
  }
  return <p role="alert">{errorMessage(t, error)}</p>;
}
