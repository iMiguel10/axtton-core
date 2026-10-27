import { useTranslation } from "react-i18next";

import { Brand } from "@/shared/components/Brand";

/**
 * Portal del cliente. El enlace secreto de F0 se retiró; el portal vuelve en F4
 * con el enlace mágico y la sesión de cliente.
 */
export function PortalApp() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto grid max-w-md gap-4 p-6">
      <Brand className="h-9" />
      <p className="text-muted-foreground">{t("portal.comingSoon")}</p>
    </main>
  );
}
