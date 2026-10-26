import { apiRequest } from "@/shared/lib/apiClient";

export const STATUSES = [
  "received",
  "diagnosing",
  "pending_approval",
  "approved",
  "in_repair",
  "waiting_parts",
  "ready",
  "delivered",
  "cancelled",
] as const;
export type Status = (typeof STATUSES)[number];

export const TYPES = ["breakdown", "maintenance", "itv", "warranty", "bodywork", "other"] as const;
export type OrderType = (typeof TYPES)[number];

export type Cause =
  | "opened"
  | "manual"
  | "quote_sent"
  | "quote_decided"
  | "quote_cancelled"
  | "undo";

export type Order = {
  id: string;
  /** OT-2026-0042 (RF-21). */
  code: string;
  year: number;
  number: number;
  type: OrderType;
  status: Status;
  unrepaired: boolean;
  vehicle: { id: string; plate: string; make: string | null; model: string | null };
  /** El titular del vehículo al abrirla: no cambia aunque cambie el titular. */
  client: { id: string; name: string; phone: string };
  responsible: { id: string; name: string } | null;
  expected_delivery_at: string | null;
  last_activity_at: string;
  created_at: string;
  /** Bloqueo optimista (RNF-15). */
  version: number;
};

export type StatusChange = {
  seq: number;
  from_status: Status | null;
  to_status: Status;
  cause: Cause;
  employee_name: string | null;
  by_client: boolean;
  note: string | null;
  created_at: string;
};

export type OrderDetail = Order & {
  no_quote_reason: string | null;
  warranty_of: { id: string; code: string } | null;
  odometer_km: number | null;
  reason: string | null;
  dropped_off_by_name: string | null;
  dropped_off_by_phone: string | null;
  reception_notes: string | null;
  delivered_at: string | null;
  history: StatusChange[];
};

export type ReceptionInput = {
  odometer_km: number | null;
  reason: string | null;
  expected_delivery_at: string | null;
  dropped_off_by_name: string | null;
  dropped_off_by_phone: string | null;
  reception_notes: string | null;
  responsible_employee_id: string | null;
};

export type OrderFilters = {
  state: "open" | "closed" | "all";
  mine?: boolean;
  sort?: "recent" | "stalled";
  vehicleId?: string;
  clientId?: string;
};

export const PAGE_SIZE = 50;

/** Sin actividad (cambio de estado o trabajo) en tantos días, se destaca (RF-24). */
export const STALLED_DAYS = 3;

export function ordersApi(workshopId: string) {
  const request = <T>(path: string, method: "GET" | "POST" | "PATCH", body?: unknown) =>
    apiRequest<T>(`/workshop/orders${path}`, { method, body, workshopId });
  return {
    list: (filters: OrderFilters, offset = 0) => {
      const params = new URLSearchParams({
        state: filters.state,
        sort: filters.sort ?? "recent",
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (filters.mine) params.set("mine", "true");
      if (filters.vehicleId) params.set("vehicle_id", filters.vehicleId);
      if (filters.clientId) params.set("client_id", filters.clientId);
      return request<Order[]>(`?${params}`, "GET");
    },
    get: (id: string) => request<OrderDetail>(`/${id}`, "GET"),
    open: (vehicleId: string, type: OrderType, input: ReceptionInput) =>
      request<{ id: string; code: string }>("", "POST", {
        vehicle_id: vehicleId,
        type,
        ...input,
      }),
    update: (order: Order, changes: Partial<ReceptionInput>) =>
      request<void>(`/${order.id}`, "PATCH", { version: order.version, ...changes }),
  };
}
