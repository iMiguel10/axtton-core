import { apiRequest } from "@/shared/lib/apiClient";

export type PartCondition = "new" | "used" | "reconditioned" | "non_specific";
export const PART_CONDITIONS: PartCondition[] = ["new", "used", "reconditioned", "non_specific"];

/** Una pieza del catálogo (RF-90). */
export type Part = {
  id: string;
  reference: string;
  description: string;
  brand: string | null;
  /** Nulo para quien no ve costes (el mecánico), o si no se sabe. */
  cost_price_cents: number | null;
  /** Nulo si el taller no deja ver importes de venta al mecánico. */
  sale_price_cents: number | null;
  vat_bp: number;
  part_condition: PartCondition;
  warranty_months: number | null;
  tracks_stock: boolean;
  /** Texto, con tres decimales ("2.000"). */
  min_stock: string | null;
  /** La suma de sus movimientos (invariante 9), como texto; nulo si no se cuenta. */
  stock: string | null;
  /** En negativo (RF-94) o por debajo del mínimo (RF-95). */
  stock_alert: StockAlert | null;
  archived_at: string | null;
  created_at: string;
  /** Se devuelve al editar: bloqueo optimista (RNF-15). */
  version: number;
};

export type StockAlert = "negative" | "below_minimum";

export type MovementKind = "in" | "out" | "adjustment" | "reversal";

/** Un apunte del libro de stock (RF-96). */
export type Movement = {
  id: string;
  seq: number;
  kind: MovementKind;
  /** Con signo: positiva entra, negativa sale. */
  quantity: string;
  /** Nulo para quien no ve costes. */
  unit_cost_cents: number | null;
  note: string | null;
  /** En un recuento, lo que se contó. */
  counted_stock: string | null;
  reverses_id: string | null;
  reversed_by_id: string | null;
  employee_name: string;
  created_at: string;
};

export type MovementPage = { movements: Movement[]; next_before: number | null };

/** Lo que se puede anular a mano: una salida se deshace en su orden. */
export const REVERSIBLE: MovementKind[] = ["in", "adjustment"];

export type PartPage = { parts: Part[]; prices_hidden: boolean };

export type PartInput = {
  reference: string;
  description: string;
  brand: string | null;
  cost_price_cents: number | null;
  sale_price_cents: number;
  /** Sin él, el alta toma el IVA por defecto del taller. */
  vat_bp?: number;
  part_condition: PartCondition;
  warranty_months: number | null;
  tracks_stock: boolean;
  min_stock: string | null;
};

export type PartFilters = { q: string; archived: boolean; alert: boolean };

export const PAGE_SIZE = 50;

export function partsApi(workshopId: string) {
  const request = <T>(path: string, method: "GET" | "POST" | "PATCH", body?: unknown) =>
    apiRequest<T>(`/workshop/parts${path}`, { method, body, workshopId });
  return {
    list: ({ q, archived, alert }: PartFilters, offset: number) => {
      const params = new URLSearchParams({
        archived: String(archived),
        alert: String(alert),
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (q.trim()) params.set("q", q.trim());
      return request<PartPage>(`?${params}`, "GET");
    },
    get: (id: string) => request<Part>(`/${id}`, "GET"),
    create: (input: PartInput) => request<{ id: string }>("", "POST", input),
    update: (part: Part, changes: Partial<PartInput>) =>
      request<void>(`/${part.id}`, "PATCH", { version: part.version, ...changes }),
    setArchived: (part: Part, archived: boolean) =>
      request<void>(`/${part.id}/${archived ? "archive" : "unarchive"}`, "POST", {
        version: part.version,
      }),
  };
}

type Created = { id: string | null };

/** El libro de stock de una pieza (RF-91 a RF-96). */
export function stockApi(workshopId: string) {
  const call = <T>(path: string, method: "GET" | "POST", body?: unknown) =>
    apiRequest<T>(`/workshop${path}`, { method, body, workshopId });
  return {
    history: (partId: string, before: number | null) =>
      call<MovementPage>(
        `/parts/${partId}/movements${before === null ? "" : `?before=${before}`}`,
        "GET",
      ),
    entry: (partId: string, body: { quantity: string; unit_cost_cents: number; note: string | null }) =>
      call<Created>(`/parts/${partId}/stock/entries`, "POST", body),
    adjust: (partId: string, body: { quantity: string; note: string }) =>
      call<Created>(`/parts/${partId}/stock/adjustments`, "POST", body),
    /** Lo contado y el stock que se veía al contar: si cambió, 409 `stock_changed`. */
    count: (partId: string, body: { counted: string; expected: string; note: string | null }) =>
      call<Created>(`/parts/${partId}/stock/count`, "POST", body),
    reverse: (movementId: string, note: string) =>
      call<Created>(`/stock-movements/${movementId}/reverse`, "POST", { note }),
  };
}
