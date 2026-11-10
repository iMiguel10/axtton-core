import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Textarea } from "@/shared/components/form/Textarea";
import { Button } from "@/shared/components/ui/button";
import { Label } from "@/shared/components/ui/label";
import { ApiError } from "@/shared/lib/apiClient";
import { errorMessage } from "@/shared/lib/errors";
import { formatEur } from "@/shared/money";

import { decideQuote, type DecisionOutcome, type PortalQuote } from "./api";

/** Lo que el portal tiene que explicar con sus palabras, no con las del taller. */
const OWN_ERRORS = new Set(["quote_not_decidable", "quote_expired"]);

function decisionError(t: TFunction, error: unknown): string {
  if (error instanceof ApiError && error.code && OWN_ERRORS.has(error.code)) {
    return t(`portal.order.decision.errors.${error.code}`);
  }
  return errorMessage(t, error);
}

/**
 * Aceptar o rechazar la versión vigente (RF-34). Lo que se decide es esta versión y
 * ninguna otra: si el taller la cambia mientras se mira, la API responde 409, la
 * orden se recarga y el mensaje se queda.
 *
 * Va sin `key`: con la versión nueva, el componente no se remonta y el error que
 * explica lo ocurrido sigue a la vista.
 */
export function DecisionPanel({ orderId, quote }: { orderId: string; quote: PortalQuote }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  // De qué versión es lo abierto: si llega otra (una recarga), se cierra solo y
  // nadie confirma un importe que no ha visto.
  const [open, setOpen] = useState<{ quoteId: string; outcome: DecisionOutcome } | null>(null);
  const [reason, setReason] = useState("");
  const decide = useMutation({
    // Sin conexión, que falle y lo diga: una decisión en pausa podría salir horas
    // después, cuando el presupuesto ya no fuera el que se vio.
    networkMode: "always",
    mutationFn: (vars: { quoteId: string; outcome: DecisionOutcome; reason: string | null }) =>
      decideQuote(vars.quoteId, { outcome: vars.outcome, reason: vars.reason }),
    onSuccess: () => {
      setOpen(null);
      setReason("");
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["portal", "orders", orderId] }),
        queryClient.invalidateQueries({ queryKey: ["portal", "vehicles"] }),
      ]),
  });

  if (decide.isSuccess && decide.variables.quoteId === quote.id) {
    return (
      <p role="status" className="rounded-lg border p-3 text-sm">
        {t(`portal.order.decision.done.${decide.variables.outcome}`)}
      </p>
    );
  }
  const error = decide.isError && (
    <p role="alert" className="text-destructive text-sm">
      {decisionError(t, decide.error)}
    </p>
  );
  if (quote.status !== "sent" || quote.decision) return error || null;

  const outcome = open?.quoteId === quote.id ? open.outcome : null;
  if (!outcome) {
    return (
      <div className="grid gap-3 border-t pt-3">
        <p className="text-sm">{t("portal.order.decision.prompt")}</p>
        {error}
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setOpen({ quoteId: quote.id, outcome: "approved" })}>
            {t("portal.order.decision.approve")}
          </Button>
          <Button variant="outline" onClick={() => setOpen({ quoteId: quote.id, outcome: "rejected" })}>
            {t("portal.order.decision.reject")}
          </Button>
        </div>
      </div>
    );
  }

  // Piezas usadas, reacondicionadas o no específicas: aceptar es dar la
  // conformidad que exige la normativa (RF-38), y tiene que quedar dicho.
  const specialParts = quote.lines.some((line) => line.part_condition && line.part_condition !== "new");
  const reasonId = `${quote.id}-reason`;
  return (
    <form
      className="grid gap-3 rounded-lg border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        decide.mutate({
          quoteId: quote.id,
          outcome,
          reason: outcome === "rejected" ? reason.trim() || null : null,
        });
      }}
    >
      <p className="font-medium">{t(`portal.order.decision.title.${outcome}`, { number: quote.version_no })}</p>
      {outcome === "approved" ? (
        <>
          <p className="text-sm">
            {t("portal.order.decision.approveText", { total: formatEur(quote.total_cents) })}
          </p>
          {specialParts && (
            <p className="text-status-pending-approval text-sm font-medium">
              {t("portal.order.decision.specialParts")}
            </p>
          )}
        </>
      ) : (
        <div className="grid gap-1">
          <Label htmlFor={reasonId}>{t("portal.order.decision.reason")}</Label>
          <Textarea
            id={reasonId}
            maxLength={2000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">{t("portal.order.decision.reasonHint")}</p>
        </div>
      )}
      <p className="text-muted-foreground text-xs">{t("portal.order.decision.final")}</p>
      {error}
      <div className="flex flex-wrap gap-2">
        <Button
          type="submit"
          variant={outcome === "rejected" ? "destructive" : "default"}
          disabled={decide.isPending}
        >
          {t(`portal.order.decision.confirm.${outcome}`)}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(null)} disabled={decide.isPending}>
          {t("common.cancel")}
        </Button>
      </div>
    </form>
  );
}
