import { TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/shared/components/ui/badge";
import { When } from "@/shared/components/When";
import { useDates } from "@/shared/lib/dates";

/** Los valores de `ClientOrderStatus` (`domain/portal.py`), nunca los internos. */
export type ClientOrderStatus =
  | "in_review"
  | "awaiting_response"
  | "in_repair"
  | "waiting_parts"
  | "ready"
  | "ready_unrepaired"
  | "delivered";

/** En qué va una orden, tal como la decide la API (especificación §6, RF-80). */
export interface ClientProgressData {
  status: ClientOrderStatus;
  updated_at: string;
  expected_delivery_at: string | null;
  delivery_overdue: boolean;
}

// Clases enteras, no compuestas: Tailwind solo genera las que ve escritas.
const STATUS_COLORS: Record<ClientOrderStatus, string> = {
  in_review: "bg-status-received/12 text-status-received border-status-received/25",
  awaiting_response:
    "bg-status-pending-approval/12 text-status-pending-approval border-status-pending-approval/25",
  in_repair: "bg-status-in-repair/12 text-status-in-repair border-status-in-repair/25",
  waiting_parts: "bg-status-waiting-parts/12 text-status-waiting-parts border-status-waiting-parts/25",
  ready: "bg-status-ready/12 text-status-ready border-status-ready/25",
  ready_unrepaired: "bg-status-ready/12 text-status-ready border-status-ready/25",
  delivered: "bg-status-delivered/12 text-status-delivered border-status-delivered/25",
};

export function ClientStatusBadge({ status }: { status: ClientOrderStatus }) {
  const { t } = useTranslation();
  return (
    <Badge variant="outline" className={STATUS_COLORS[status]}>
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {t(`portal.progress.statuses.${status}`)}
    </Badge>
  );
}

/**
 * La fecha de la última actualización y la entrega prevista. Si esa fecha ya
 * pasó, lo dice en vez de enseñarla como si valiera (RF-80).
 */
export function ProgressDetails({ progress }: { progress: ClientProgressData }) {
  const { t } = useTranslation();
  const dates = useDates();
  const expected = dates.date(progress.expected_delivery_at);
  return (
    <div className="text-muted-foreground grid gap-1 text-sm">
      <p>
        {t("portal.progress.updated")} <When iso={progress.updated_at} />
      </p>
      {expected && progress.delivery_overdue && (
        <p className="text-status-pending-approval flex items-start gap-1.5">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
          {t("portal.progress.overdue", { date: expected })}
        </p>
      )}
      {expected && !progress.delivery_overdue && (
        <p>
          {t("portal.progress.expected")}: {expected}
        </p>
      )}
    </div>
  );
}
