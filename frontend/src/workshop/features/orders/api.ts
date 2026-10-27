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
  /** Si es un deshacer, el `seq` del cambio que compensa. */
  undoes_seq: number | null;
  employee_name: string | null;
  by_client: boolean;
  note: string | null;
  created_at: string;
};

export type AllowedTransition = { to_status: Status; needs_note: boolean; unrepaired: boolean };

export type NoQuoteReason = "waiver" | "warranty" | "fixed_price";

export type OrderDetail = Order & {
  no_quote_reason: NoQuoteReason | null;
  warranty_of: { id: string; code: string } | null;
  odometer_km: number | null;
  reason: string | null;
  dropped_off_by_name: string | null;
  dropped_off_by_phone: string | null;
  reception_notes: string | null;
  delivered_at: string | null;
  history: StatusChange[];
  /** Lo que puede hacer quien la mira: el servidor lo vuelve a comprobar. */
  allowed_transitions: AllowedTransition[];
  can_undo: boolean;
  can_mark_no_quote: boolean;
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
    changeStatus: (order: Order, to: Status, note: string | null) =>
      request<void>(`/${order.id}/status`, "POST", {
        version: order.version,
        to_status: to,
        note,
      }),
    undo: (order: Order) =>
      request<void>(`/${order.id}/undo`, "POST", { version: order.version }),
    setNoQuote: (order: Order, reason: NoQuoteReason | null) =>
      request<void>(`/${order.id}/no-quote`, "POST", { version: order.version, reason }),
  };
}

// --- Diagnóstico, notas y trabajos (RF-22, RF-23) ---------------------------

export type DiagnosisVersion = {
  version_no: number;
  text: string;
  employee_name: string;
  created_at: string;
};

export type Note = { seq: number; body: string; employee_name: string; created_at: string };

export type WorkEntry = {
  id: string;
  employee: { id: string; name: string };
  recorded_by_name: string;
  description: string;
  worked_on: string;
  /** Decimal: llega como texto ("1.50"). */
  hours: string | null;
  voided_at: string | null;
  can_void: boolean;
};

export type Worklog = {
  /** La vigente primero; vacío si aún no hay. */
  diagnosis: DiagnosisVersion[];
  notes: Note[];
  work_entries: WorkEntry[];
  workers: string[];
};

export type WorkEntryInput = {
  /** El del borrador: reenviarlo no anota dos veces el mismo trabajo (RNF-22). */
  id: string;
  employee_id: string;
  description: string;
  worked_on: string;
  hours: string | null;
};

export function worklogApi(workshopId: string, orderId: string) {
  const request = <T>(path: string, method: "GET" | "POST", body?: unknown) =>
    apiRequest<T>(`/workshop/orders/${orderId}${path}`, { method, body, workshopId });
  return {
    get: () => request<Worklog>("/worklog", "GET"),
    /** `base` es la versión desde la que se editó (0 si no había): RNF-15. */
    saveDiagnosis: (base: number, text: string) =>
      request<{ version_no: number }>("/diagnosis", "POST", { base_version_no: base, text }),
    /** `id` es el del borrador, como en `addWork`. */
    addNote: (id: string, body: string) => request<void>("/notes", "POST", { id, body }),
    addWork: (input: WorkEntryInput) =>
      request<{ id: string }>("/work-entries", "POST", input),
    voidWork: (entryId: string) => request<void>(`/work-entries/${entryId}/void`, "POST"),
  };
}

export type StaffMember = { id: string; name: string };

export const fetchStaff = (workshopId: string) =>
  apiRequest<StaffMember[]>("/workshop/staff", { workshopId });
