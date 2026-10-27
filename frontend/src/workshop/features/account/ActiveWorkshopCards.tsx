import { useQuery } from "@tanstack/react-query";
import { Building2, ChevronRight, IdCard, ScrollText, Settings2, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/components/ui/card";

import { fetchStaff } from "../orders/api";
import { useActiveWorkshop } from "../session/ActiveWorkshop";

/**
 * La parte de "Mi cuenta" que es del taller activo: dónde estoy, con qué ficha y
 * rol, a qué otros talleres puedo pasar y, si lo administro, lo que se configura.
 */
export function ActiveWorkshopCards() {
  return (
    <>
      <WorkshopCard />
      <SettingsCard />
    </>
  );
}

function WorkshopCard() {
  const { t } = useTranslation();
  const { workshopId, workshopName, employeeId, role, workshops, select } = useActiveWorkshop();
  const staff = useQuery({
    queryKey: ["staff", workshopId],
    queryFn: () => fetchStaff(workshopId),
    staleTime: 60_000,
  });
  const me = staff.data?.find((member) => member.id === employeeId);
  const others = workshops.filter((w) => w.workshop_id !== workshopId);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("account.activeWorkshop")}</CardTitle>
        <CardDescription>{t("account.activeWorkshopHint")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="flex items-center gap-3">
          <span className="bg-muted flex size-11 shrink-0 items-center justify-center rounded-lg">
            <Building2 className="size-5" />
          </span>
          <div className="grid">
            <span className="font-medium">{workshopName}</span>
            <span className="text-muted-foreground text-sm">
              {me?.name ?? "—"} · {t(`roles.${role}`)}
            </span>
          </div>
        </div>
        {others.length > 0 && (
          <div className="grid gap-2">
            <span className="text-muted-foreground text-sm">{t("account.otherWorkshops")}</span>
            {others.map((w) => (
              <div key={w.workshop_id} className="flex items-center justify-between gap-2 rounded-lg border p-2 pl-3">
                <span className="text-sm">
                  {w.workshop_name}{" "}
                  <Badge variant="outline" className="ml-1">
                    {t(`roles.${w.role}`)}
                  </Badge>
                </span>
                <Button size="sm" variant="outline" onClick={() => select(w.workshop_id)}>
                  {t("account.switchTo")}
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

type Setting = { to: string; icon: LucideIcon; title: string; hint: string };

/** Lo que el administrador configura del taller. Solo lo que existe hoy. */
function SettingsCard() {
  const { t } = useTranslation();
  const { canManageEmployees, canViewAudit } = useActiveWorkshop();
  const settings: Setting[] = [
    ...(canManageEmployees
      ? [{ to: "/employees", icon: IdCard, title: t("nav.employees"), hint: t("account.settings.employees") }]
      : []),
    ...(canViewAudit
      ? [{ to: "/audit", icon: ScrollText, title: t("nav.audit"), hint: t("account.settings.audit") }]
      : []),
  ];
  if (settings.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("account.settings.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2">
        {settings.map((setting) => (
          <Link
            key={setting.to}
            to={setting.to}
            className="hover:bg-muted flex items-center gap-3 rounded-lg border p-3 transition-colors"
          >
            <setting.icon className="text-muted-foreground size-5 shrink-0" />
            <span className="grid flex-1">
              <span className="font-medium">{setting.title}</span>
              <span className="text-muted-foreground text-sm">{setting.hint}</span>
            </span>
            <ChevronRight className="text-muted-foreground size-4" />
          </Link>
        ))}
        {/* Los datos del taller llegan con los presupuestos (RF-02, F3). */}
        <div className="flex items-center gap-3 rounded-lg border border-dashed p-3 opacity-70">
          <Settings2 className="text-muted-foreground size-5 shrink-0" />
          <span className="grid flex-1">
            <span className="font-medium">{t("account.settings.workshopData")}</span>
            <span className="text-muted-foreground text-sm">{t("account.settings.workshopDataHint")}</span>
          </span>
          <Badge variant="outline">{t("account.settings.soon")}</Badge>
        </div>
      </CardContent>
    </Card>
  );
}
