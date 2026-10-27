import { useTranslation } from "react-i18next";

import { apiRequest } from "@/shared/lib/apiClient";
import { cn } from "@/shared/lib/utils";

/** Lo que limita domain/limits.py, en su orden. */
export type LimitResource =
  | "employees_with_access"
  | "employees"
  | "clients"
  | "vehicles"
  | "orders_per_month";

export type LimitUsage = { resource: LimitResource; used: number; limit: number };

/** Los límites del taller activo, para su administrador (§10). */
export const fetchWorkshopLimits = (workshopId: string) =>
  apiRequest<LimitUsage[]>("/workshop/limits", { workshopId });

/** Desde el 80 % se avisa: aún cabe, pero queda poco. */
const WARN_AT = 0.8;

/**
 * Lo gastado de cada límite, con una barra: en ámbar cuando queda poco y en rojo
 * cuando está lleno. La usan el superadministrador (en /admin) y el
 * administrador del taller (en su cuenta).
 */
export function LimitBars({ limits }: { limits: LimitUsage[] }) {
  const { t, i18n } = useTranslation();
  const number = (n: number) => n.toLocaleString(i18n.language);
  return (
    <ul className="grid gap-3">
      {limits.map(({ resource, used, limit }) => {
        const ratio = Math.min(used / limit, 1);
        return (
          <li key={resource} className="grid gap-1">
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span>{t(`limits.resources.${resource}`)}</span>
              <span className="text-muted-foreground tabular-nums">
                {t("limits.usedOf", { used: number(used), limit: number(limit) })}
              </span>
            </div>
            <div
              role="meter"
              aria-label={t(`limits.resources.${resource}`)}
              aria-valuemin={0}
              aria-valuemax={limit}
              aria-valuenow={used}
              className="bg-muted h-1.5 overflow-hidden rounded-full"
            >
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  ratio >= 1 ? "bg-destructive" : ratio >= WARN_AT ? "bg-status-waiting-parts" : "bg-success",
                )}
                style={{ width: `${Math.max(ratio * 100, used > 0 ? 2 : 0)}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
