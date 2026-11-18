import { useTranslation } from "react-i18next";

import { useDates } from "@/shared/lib/dates";

import type { OrderDetail } from "./api";

/** Los datos de recepción de la orden, para leerlos (RF-20, RF-51): en la ficha
 * de una orden que no se edita y en la pantalla donde el cliente firma. */
export function ReceptionSummary({
  order,
  forClient = false,
}: {
  order: OrderDetail;
  /** Para quien firma: sin el responsable, que es interno, y sin la renuncia,
   * que la pantalla de firma enseña aparte con su texto. */
  forClient?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const dates = useDates();
  const droppedOff = [order.dropped_off_by_name, order.dropped_off_by_phone]
    .filter(Boolean)
    .join(" · ");
  const rows: [string, string | null][] = [
    [t("orders.reason"), order.reason],
    [t("orders.odometer"), order.odometer_km?.toLocaleString(i18n.language) ?? null],
    [t("orders.expectedDelivery"), dates.dateTime(order.expected_delivery_at)],
    ...(forClient
      ? []
      : ([[t("orders.responsible"), order.responsible?.name ?? null]] as [string, string | null][])),
    [t("orders.droppedOffBy"), droppedOff || null],
    [t("orders.fuelLevel"), order.fuel_level && t(`orders.fuel.${order.fuel_level}`)],
    [t("orders.visibleDamage"), order.visible_damage],
    [t("orders.belongings"), order.belongings],
    ...(forClient
      ? []
      : ([[t("orders.quoteWaived"), order.quote_waived ? t("orders.quoteWaivedYes") : null]] as [
          string,
          string | null,
        ][])),
  ];
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[max-content_1fr]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground text-sm">{label}</dt>
          <dd className="whitespace-pre-line">{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
