import { apiRequest } from "@/shared/lib/apiClient";

export const QUOTE_STATUSES = [
  "draft",
  "sent",
  "approved",
  "rejected",
  "expired",
  "superseded",
  "cancelled",
] as const;
export type QuoteStatus = (typeof QUOTE_STATUSES)[number];
export const LINE_KINDS = ["labor", "part", "other"] as const;
export type LineKind = (typeof LINE_KINDS)[number];
export const PART_CONDITIONS = ["new", "used", "reconditioned", "non_specific"] as const;
export type PartCondition = (typeof PART_CONDITIONS)[number];
export type DiscountKind = "percent" | "amount";

export type QuoteLine = {
  id: string;
  position: number;
  kind: LineKind;
  description: string;
  reference: string | null;
  part_condition: PartCondition | null;
  /** Decimal como texto ("1.500"): tres decimales, por los litros de aceite. */
  quantity: string;
  /** Nulos si el taller no deja ver importes al mecánico. */
  unit_price_cents: number | null;
  discount_bp: number;
  vat_bp: number;
  taxable_cents: number | null;
  total_cents: number | null;
};

export type QuoteTotals = {
  subtotal_cents: number;
  global_discount_cents: number;
  vat_breakdown: { vat_bp: number; base_cents: number; vat_cents: number }[];
  total_cents: number;
};

export type Quote = {
  id: string;
  version_no: number;
  status: QuoteStatus;
  created_at: string;
  sent_at: string | null;
  valid_until: string | null;
  cancel_reason: string | null;
  global_discount_kind: DiscountKind | null;
  global_discount_value: number | null;
  lines: QuoteLine[];
  /** En un borrador, lo que saldría si se enviara ahora (lo calcula la API). */
  totals: QuoteTotals | null;
  prices_hidden: boolean;
  /** Enviada y fuera de plazo, aunque su estado aún diga "enviada" (hasta F5). */
  expired: boolean;
  version: number;
};

export type QuoteLineInput = {
  kind: LineKind;
  description: string;
  reference: string | null;
  part_condition: PartCondition | null;
  quantity: string;
  unit_price_cents: number;
  discount_bp: number;
  vat_bp: number;
};

export type DraftInput = {
  global_discount: { kind: DiscountKind; value: number } | null;
  lines: QuoteLineInput[];
};

/** Los filtros del listado de la barra lateral. */
export const QUOTE_VIEWS = ["pending", "expired", "drafts", "all"] as const;
export type QuoteView = (typeof QUOTE_VIEWS)[number];
export const QUOTES_PAGE_SIZE = 50;

export type QuoteListItem = {
  id: string;
  order_id: string;
  order_code: string;
  plate: string;
  /** Vacío si el cliente se anonimizó: se enseña con clientName(). */
  client_name: string;
  version_no: number;
  status: QuoteStatus;
  /** Enviada y fuera de plazo, aunque su estado aún diga "enviada". */
  expired: boolean;
  total_cents: number | null;
  sent_at: string | null;
  valid_until: string | null;
  updated_at: string;
};

export function quotesApi(workshopId: string) {
  const request = <T>(path: string, method: "GET" | "POST" | "PUT", body?: unknown) =>
    apiRequest<T>(path, { method, body, workshopId });
  return {
    listAll: (view: QuoteView, offset: number) =>
      request<QuoteListItem[]>(
        `/workshop/quotes?${new URLSearchParams({ view, limit: String(QUOTES_PAGE_SIZE), offset: String(offset) })}`,
        "GET",
      ),
    list: (orderId: string) => request<Quote[]>(`/workshop/orders/${orderId}/quotes`, "GET"),
    create: (orderId: string) =>
      request<{ id: string }>(`/workshop/orders/${orderId}/quotes`, "POST"),
    save: (quoteId: string, version: number, input: DraftInput) =>
      request<{ version: number }>(`/workshop/quotes/${quoteId}`, "PUT", { version, ...input }),
    discard: (quoteId: string, version: number) =>
      request<void>(`/workshop/quotes/${quoteId}/discard`, "POST", { version }),
    send: (quoteId: string, version: number) =>
      request<void>(`/workshop/quotes/${quoteId}/send`, "POST", { version }),
    cancel: (quoteId: string, version: number, reason: string) =>
      request<void>(`/workshop/quotes/${quoteId}/cancel`, "POST", { version, reason }),
    renew: (quoteId: string, version: number) =>
      request<{ id: string }>(`/workshop/quotes/${quoteId}/renew`, "POST", { version }),
  };
}
