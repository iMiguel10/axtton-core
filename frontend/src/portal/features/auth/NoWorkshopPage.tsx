import { useTranslation } from "react-i18next";

import { AuthLayout } from "@/shared/components/AuthLayout";

/**
 * `/portal/login` sin taller. No pide el email: el enlace es siempre de un taller,
 * y se pide desde su página de entrada (decisión 0006). Una lista de talleres aquí
 * sería pública, sin sesión.
 */
export function NoWorkshopPage() {
  const { t } = useTranslation();
  return (
    <AuthLayout
      title={t("portal.noWorkshop.title")}
      description={t("portal.noWorkshop.description")}
      tagline={t("portal.tagline")}
    >
      <p className="text-muted-foreground text-center text-sm">{t("portal.noWorkshop.hint")}</p>
    </AuthLayout>
  );
}
