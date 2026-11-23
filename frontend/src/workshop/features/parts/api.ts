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
  archived_at: string | null;
  created_at: string;
  /** Se devuelve al editar: bloqueo optimista (RNF-15). */
  version: number;
};

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

export type PartFilters = { q: string; archived: boolean };

export const PAGE_SIZE = 50;

export function partsApi(workshopId: string) {
  const request = <T>(path: string, method: "GET" | "POST" | "PATCH", body?: unknown) =>
    apiRequest<T>(`/workshop/parts${path}`, { method, body, workshopId });
  return {
    list: ({ q, archived }: PartFilters, offset: number) => {
      const params = new URLSearchParams({
        archived: String(archived),
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
