import { useTranslation } from "react-i18next";

import { useActiveWorkshop } from "../session/ActiveWorkshop";

/** Inicio del taller. Las órdenes, clientes y vehículos llegan en F2. */
export function HomePage() {
  const { t } = useTranslation();
  const { workshopName, role } = useActiveWorkshop();
  return (
    <section className="grid gap-2">
      <h1 className="text-2xl font-semibold">{workshopName}</h1>
      <p className="text-muted-foreground">
        {t("home.yourRole", { role: t(`roles.${role}`) })}
      </p>
      <p>{t("home.comingSoon")}</p>
    </section>
  );
}
