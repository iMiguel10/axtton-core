import { useQuery } from "@tanstack/react-query";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { ordersApi, type OrderNotice } from "./api";

/** Puede cambiar sin que nadie toque la orden: en cola, enviándose o esperando reintento. */
export function inFlight(notice: OrderNotice): boolean {
  return (
    notice.status === "pending" ||
    notice.status === "claimed" ||
    (notice.status === "failed" && notice.next_attempt_at !== null)
  );
}

/**
 * Los avisos al cliente de una orden (RF-69). La clave cuelga de la de la ficha:
 * lo que la recarga (enviar un presupuesto, marcarla lista) recarga también los
 * avisos. Los cambia el worker, no la ficha, así que mientras alguno siga en
 * marcha se vuelven a pedir cada 30 segundos.
 */
export function useOrderNotices(orderId: string) {
  const { workshopId } = useActiveWorkshop();
  return useQuery({
    queryKey: ["order", workshopId, orderId, "notifications"],
    queryFn: () => ordersApi(workshopId).notifications(orderId),
    refetchInterval: (query) => (query.state.data?.some(inFlight) ? 30_000 : false),
  });
}
