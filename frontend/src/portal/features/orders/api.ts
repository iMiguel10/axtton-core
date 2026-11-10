import { apiRequest } from "@/shared/lib/apiClient";

import type { ClientProgressData } from "./ClientProgress";

export type OrderSummary = {
  id: string;
  code: string;
  opened_at: string;
  progress: ClientProgressData;
};

export type VehicleInfo = { plate: string; make: string | null; model: string | null };

export type PortalVehicle = VehicleInfo & { orders: OrderSummary[] };

export type QuoteStatus = "sent" | "approved" | "rejected" | "expired" | "superseded" | "cancelled";

export type QuoteLine = {
  kind: "labor" | "part" | "other";
  description: string;
  reference: string | null;
  part_condition: "new" | "used" | "reconditioned" | "non_specific" | null;
  quantity: string;
  unit_price_cents: number;
  discount_bp: number;
  vat_bp: number;
  amount_cents: number;
};

export type PortalQuote = {
  id: string;
  version_no: number;
  status: QuoteStatus;
  sent_at: string | null;
  valid_until: string | null;
  delivery_business_days: number | null;
  delivery_on: string | null;
  lines: QuoteLine[];
  subtotal_cents: number;
  global_discount_cents: number;
  vat_breakdown: { vat_bp: number; base_cents: number; vat_cents: number }[];
  total_cents: number;
  decision: {
    outcome: DecisionOutcome;
    channel: "portal" | "phone" | "in_person";
    decided_at: string;
  } | null;
};

export type PortalOrderDetail = {
  id: string;
  code: string;
  opened_at: string;
  progress: ClientProgressData;
  vehicle: VehicleInfo;
  diagnosis: { text: string; updated_at: string } | null;
  /** La primera es la vigente; las demás, las versiones anteriores. */
  quotes: PortalQuote[];
  work: { description: string; worked_on: string }[];
};

export function fetchVehicles(): Promise<PortalVehicle[]> {
  return apiRequest("/portal/vehicles");
}

export function fetchOrder(orderId: string): Promise<PortalOrderDetail> {
  return apiRequest(`/portal/orders/${encodeURIComponent(orderId)}`);
}

export type DecisionOutcome = "approved" | "rejected";

/** Aceptar o rechazar una versión (RF-34). El motivo, solo al rechazar. */
export function decideQuote(
  quoteId: string,
  body: { outcome: DecisionOutcome; reason: string | null },
): Promise<void> {
  return apiRequest(`/portal/quotes/${encodeURIComponent(quoteId)}/decision`, { method: "POST", body });
}

/** "Seat Ibiza", o nada si el taller no apuntó marca ni modelo. */
export function makeAndModel(vehicle: VehicleInfo): string {
  return [vehicle.make, vehicle.model].filter(Boolean).join(" ");
}
