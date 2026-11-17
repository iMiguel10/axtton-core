import { Mail } from "lucide-react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/shared/components/EmptyState";
import { LinesSkeleton } from "@/shared/components/Loading";
import { When } from "@/shared/components/When";
import { Badge } from "@/shared/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { errorMessage } from "@/shared/lib/errors";

import type { OrderNotice } from "./api";
import { useOrderNotices } from "./useOrderNotices";

/** Lo que el taller lee de un aviso: el estado, separando el fallido que aún se
 * reintenta del que ya no. */
type NoticeState =
  | "pending"
  | "claimed"
  | "sent"
  | "retrying"
  | "failed"
  | "unknown"
  | "cancelled"
  | "skipped";

function stateOf(notice: OrderNotice): NoticeState {
  if (notice.status === "failed") return notice.next_attempt_at ? "retrying" : "failed";
  return notice.status;
}

// Los colores de los estados de la orden (tokens --status-*): verde lo que salió,
// rojo y naranja lo que pide llamar al cliente, gris lo que no hay que hacer nada.
// Clases enteras: Tailwind solo genera las que ve escritas.
const STATE_COLORS: Record<NoticeState, string> = {
  pending: "bg-status-received/12 text-status-received border-status-received/25",
  claimed: "bg-status-in-repair/12 text-status-in-repair border-status-in-repair/25",
  sent: "bg-status-ready/12 text-status-ready border-status-ready/25",
  retrying: "bg-status-waiting-parts/12 text-status-waiting-parts border-status-waiting-parts/25",
  failed: "bg-status-cancelled/12 text-status-cancelled border-status-cancelled/25",
  unknown:
    "bg-status-pending-approval/12 text-status-pending-approval border-status-pending-approval/25",
  cancelled: "bg-status-received/12 text-status-received border-status-received/25",
  skipped: "bg-status-received/12 text-status-received border-status-received/25",
};

/**
 * Los avisos al cliente de una orden (RF-69): qué se le envió y, lo que no
 * salió, por qué y qué hacer. El motivo llega como código y se explica aquí.
 */
export function NoticesSection({ orderId }: { orderId: string }) {
  const { t } = useTranslation();
  const notices = useOrderNotices(orderId);
  if (!notices.data) {
    return notices.isError ? (
      <p role="alert" className="text-destructive text-sm">
        {errorMessage(t, notices.error)}
      </p>
    ) : (
      <LinesSkeleton lines={3} />
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("notices.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {notices.data.length === 0 ? (
          <EmptyState compact icon={Mail} title={t("notices.none")} description={t("notices.noneHint")} />
        ) : (
          <ul className="divide-y">
            {notices.data.map((notice) => (
              <NoticeRow key={notice.id} notice={notice} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function NoticeRow({ notice }: { notice: OrderNotice }) {
  const { t } = useTranslation();
  const state = stateOf(notice);
  return (
    <li className="grid gap-1 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">
          {t(`notices.kinds.${notice.kind}`, { version: notice.quote_version_no })}
        </span>
        <Badge variant="outline" className={STATE_COLORS[state]}>
          <span aria-hidden className="size-1.5 rounded-full bg-current" />
          {t(`notices.states.${state}`)}
        </Badge>
      </div>
      <span className="text-muted-foreground text-sm">
        {notice.sent_at ? (
          <>
            {t("notices.sentAt")} <When iso={notice.sent_at} />
          </>
        ) : (
          <>
            {t("notices.createdAt")} <When iso={notice.created_at} />
          </>
        )}
        {notice.attempts > 1 && ` · ${t("notices.attempts", { count: notice.attempts })}`}
      </span>
      <Explanation notice={notice} state={state} />
    </li>
  );
}

/** Qué ha pasado con un aviso que no salió, o cuándo saldrá. */
function Explanation({ notice, state }: { notice: OrderNotice; state: NoticeState }) {
  const { t } = useTranslation();
  if (state === "sent") return null;
  if (state === "pending" || state === "claimed") {
    return <p className="text-muted-foreground text-sm">{t("notices.pendingHint")}</p>;
  }
  return (
    <p className="text-sm">
      {/* "Ya no hacía falta" depende de qué avisaba: lo que dejó de ser cierto. */}
      {notice.failure_reason === "obsolete"
        ? t(`notices.obsolete.${notice.kind}`)
        : notice.failure_reason && t(`notices.reasons.${notice.failure_reason}`)}
      {notice.smtp_code !== null && ` ${t("notices.smtpCode", { code: notice.smtp_code })}`}
      {state === "retrying" && notice.next_attempt_at && (
        <>
          {" "}
          {t("notices.retryAt")} <When iso={notice.next_attempt_at} />.
        </>
      )}
      {state === "failed" && ` ${t("notices.gaveUp")}`}
    </p>
  );
}
