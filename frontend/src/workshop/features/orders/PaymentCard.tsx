import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Field } from "@/shared/components/form/Field";
import { Select } from "@/shared/components/form/Select";
import { Badge } from "@/shared/components/ui/badge";
import { Button } from "@/shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Label } from "@/shared/components/ui/label";
import { errorMessage } from "@/shared/lib/errors";
import { formatEur, parseEurToCents } from "@/shared/money";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { ordersApi, type OrderDetail, type PaymentMethod, type PaymentStatus } from "./api";

const STATUSES: PaymentStatus[] = ["pending", "paid", "no_charge"];
const METHODS: PaymentMethod[] = ["cash", "card", "transfer", "other"];

/** 18950 → "189,50", para volver a editarlo. */
function centsToInput(cents: number | null): string {
  return cents === null ? "" : (cents / 100).toFixed(2).replace(".", ",");
}

function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * El cobro de una orden cerrada (RF-26, RF-28): cobrada, pendiente o sin
 * cargo. Una marca operativa, no una factura: se puede corregir, y cada cambio
 * queda en la auditoría. El importe lo escribe quien cobra (con F3, lo
 * propondrá el presupuesto aceptado). Sin `key` por versión, como StatusCard:
 * tras un 409 el error tiene que seguir a la vista.
 */
export function PaymentCard({
  order,
  onChanged,
}: {
  order: OrderDetail;
  onChanged: () => Promise<unknown>;
}) {
  const { t, i18n } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState<PaymentStatus>(order.payment_status);
  const [method, setMethod] = useState<PaymentMethod>(order.payment_method ?? "card");
  const [amount, setAmount] = useState(() => centsToInput(order.paid_amount_cents));
  const [paidOn, setPaidOn] = useState(() => order.paid_on ?? today());
  const cents = parseEurToCents(amount);
  const save = useMutation({
    mutationFn: () =>
      ordersApi(workshopId).recordPayment(
        order,
        status === "paid"
          ? { status, method, amount_cents: cents, paid_on: paidOn }
          : { status, method: null, amount_cents: null, paid_on: null },
      ),
    onSuccess: () => setEditing(false),
    onSettled: onChanged,
  });
  const invalid = status === "paid" && (cents === null || cents <= 0 || !paidOn);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("payment.title")}</CardTitle>
        <Badge variant={order.payment_status === "pending" ? "outline" : "secondary"}>
          {t(`payment.statuses.${order.payment_status}`)}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-3">
        {order.payment_status === "paid" && order.paid_amount_cents !== null && order.paid_on && (
          <p className="text-sm">
            {t("payment.summary", {
              amount: formatEur(order.paid_amount_cents),
              method: t(`payment.methods.${order.payment_method}`).toLowerCase(),
              date: new Date(`${order.paid_on}T00:00:00`).toLocaleDateString(i18n.language),
            })}
          </p>
        )}
        {save.isError && (
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(t, save.error)}
          </p>
        )}
        {order.can_record_payment &&
          (editing ? (
            <form
              className="grid gap-3 md:grid-cols-4 md:items-end"
              onSubmit={(event) => {
                event.preventDefault();
                save.mutate();
              }}
            >
              <div className="grid gap-1.5">
                <Label htmlFor="payment-status">{t("payment.status")}</Label>
                <Select
                  id="payment-status"
                  value={status}
                  onChange={(event) => setStatus(event.target.value as PaymentStatus)}
                >
                  {STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {t(`payment.statuses.${value}`)}
                    </option>
                  ))}
                </Select>
              </div>
              {status === "paid" && (
                <>
                  <div className="grid gap-1.5">
                    <Label htmlFor="payment-method">{t("payment.method")}</Label>
                    <Select
                      id="payment-method"
                      value={method}
                      onChange={(event) => setMethod(event.target.value as PaymentMethod)}
                    >
                      {METHODS.map((value) => (
                        <option key={value} value={value}>
                          {t(`payment.methods.${value}`)}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <Field
                    id="payment-amount"
                    label={t("payment.amount")}
                    inputMode="decimal"
                    required
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                  />
                  <Field
                    id="payment-date"
                    type="date"
                    label={t("payment.date")}
                    required
                    max={today()}
                    value={paidOn}
                    onChange={(event) => setPaidOn(event.target.value)}
                  />
                </>
              )}
              <div className="flex gap-2 md:col-span-4">
                <Button type="submit" size="sm" disabled={save.isPending || invalid}>
                  {t("common.save")}
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)}>
                  {t("common.cancel")}
                </Button>
              </div>
            </form>
          ) : (
            <div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  // Desde lo guardado ahora, no desde lo que había al montar.
                  setStatus(order.payment_status === "pending" ? "paid" : order.payment_status);
                  setMethod(order.payment_method ?? "card");
                  setAmount(centsToInput(order.paid_amount_cents));
                  setPaidOn(order.paid_on ?? today());
                  save.reset();
                  setEditing(true);
                }}
              >
                {t(order.payment_status === "pending" ? "payment.record" : "payment.change")}
              </Button>
            </div>
          ))}
      </CardContent>
    </Card>
  );
}
