import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmButton } from "@/shared/components/ConfirmButton";
import { Select } from "@/shared/components/form/Select";
import { Textarea } from "@/shared/components/form/Textarea";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Label } from "@/shared/components/ui/label";
import { errorMessage } from "@/shared/lib/errors";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { ordersApi, type AllowedTransition, type NoQuoteReason, type OrderDetail } from "./api";
import { StatusBadge } from "./OrderBits";

/**
 * Mover la orden por su ciclo de vida (especificación §6). Los botones salen de
 * `allowed_transitions`, que calcula el servidor con el rol de quien mira: la
 * interfaz no repite las reglas, y el servidor las vuelve a comprobar al pedir.
 * Sin `key={order.version}`: tras un 409 la ficha se recarga con otra versión, y
 * remontar la tarjeta borraría el mensaje de error antes de poder leerlo.
 */
export function StatusCard({
  order,
  onChanged,
}: {
  order: OrderDetail;
  /** Haya ido bien o no (un 409): la ficha se vuelve a pedir. */
  onChanged: () => Promise<unknown>;
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const api = ordersApi(workshopId);
  // La transición que pide nota, mientras se escribe.
  const [pending, setPending] = useState<AllowedTransition | null>(null);
  const [note, setNote] = useState("");

  const action = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: () => {
      setPending(null);
      setNote("");
    },
    onSettled: onChanged,
  });
  const run = (call: () => Promise<unknown>) => action.mutate(call);

  const choose = (transition: AllowedTransition) => {
    if (transition.needs_note) {
      setPending(transition);
      return;
    }
    run(() => api.changeStatus(order, transition.to_status, null));
  };
  const label = (transition: AllowedTransition) =>
    t(transition.unrepaired ? "orders.transitions.unrepaired" : `orders.transitions.${transition.to_status}`);
  const lastChange = order.history[order.history.length - 1];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("orders.statusTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={order.status} unrepaired={order.unrepaired} />
          {order.no_quote_reason && (
            <span className="text-muted-foreground text-sm">
              {t("orders.noQuote")}: {t(`orders.noQuoteReasons.${order.no_quote_reason}`)}
            </span>
          )}
        </div>
        {action.isError && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, action.error)}
          </p>
        )}
        {order.allowed_transitions.length > 0 && !pending && (
          <div className="flex flex-wrap gap-2">
            {order.allowed_transitions.map((transition) => (
              <Button
                key={`${transition.to_status}-${transition.unrepaired}`}
                variant={transition.to_status === "cancelled" ? "destructive" : "default"}
                disabled={action.isPending}
                onClick={() => choose(transition)}
              >
                {label(transition)}
              </Button>
            ))}
          </div>
        )}
        {pending && (
          <form
            className="grid gap-2 rounded-lg border p-3"
            onSubmit={(event) => {
              event.preventDefault();
              run(() => api.changeStatus(order, pending.to_status, note));
            }}
          >
            <Label htmlFor="status-note">
              {t(pending.unrepaired ? "orders.noteUnrepaired" : "orders.noteCancel")}
            </Label>
            <Textarea
              id="status-note"
              required
              autoFocus
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={!note.trim() || action.isPending}>
                {label(pending)}
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setPending(null)}>
                {t("common.cancel")}
              </Button>
            </div>
          </form>
        )}
        {order.can_undo && (
          <div>
            <ConfirmButton
              variant="outline"
              size="sm"
              disabled={action.isPending}
              title={t("orders.undo")}
              description={t("orders.confirmUndo", {
                status: t(`orders.statuses.${lastChange.from_status ?? order.status}`),
              })}
              confirmLabel={t("orders.undo")}
              onConfirm={() => run(() => api.undo(order))}
            >
              {t("orders.undo")}
            </ConfirmButton>
          </div>
        )}
        {order.can_mark_no_quote && (
          <NoQuoteControl
            // Lo guardado manda: al cambiar, el desplegable vuelve a empezar.
            key={order.no_quote_reason ?? ""}
            current={order.no_quote_reason}
            disabled={action.isPending}
            onSave={(reason) => run(() => api.setNoQuote(order, reason))}
          />
        )}
      </CardContent>
    </Card>
  );
}

/** "Sin presupuesto" (RF-27). La renuncia del cliente no se ofrece: exige la
 * hoja de recepción firmada, que llega en F6. */
function NoQuoteControl({
  current,
  disabled,
  onSave,
}: {
  current: NoQuoteReason | null;
  disabled: boolean;
  onSave: (reason: NoQuoteReason | null) => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState<string>(current ?? "");
  return (
    <div className="grid gap-1.5 border-t pt-3">
      <Label htmlFor="no-quote">{t("orders.noQuote")}</Label>
      <div className="flex flex-wrap gap-2">
        <Select id="no-quote" value={reason} onChange={(event) => setReason(event.target.value)}>
          <option value="">{t("orders.noQuoteNone")}</option>
          <option value="warranty">{t("orders.noQuoteReasons.warranty")}</option>
          <option value="fixed_price">{t("orders.noQuoteReasons.fixed_price")}</option>
        </Select>
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || reason === (current ?? "")}
          onClick={() => onSave((reason || null) as NoQuoteReason | null)}
        >
          {t("common.save")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("orders.noQuoteHint")}</p>
    </div>
  );
}
