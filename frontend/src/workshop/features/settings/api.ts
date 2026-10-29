import { apiBlob, apiRequest } from "@/shared/lib/apiClient";

export type WorkshopSettings = {
  name: string;
  legal_name: string | null;
  tax_id: string | null;
  address: string | null;
  phone: string | null;
  reply_to_email: string | null;
  industrial_registry_number: string | null;
  /** Puntos básicos: 2100 = 21 %. */
  default_vat_bp: number;
  quote_validity_business_days: number;
  mechanics_see_sale_prices: boolean;
  /** Solo lectura: la fija la plataforma. */
  timezone: string;
  has_logo: boolean;
  /** Se devuelve al guardar: bloqueo optimista (RNF-15). */
  version: number;
};

export type WorkshopSettingsInput = Omit<WorkshopSettings, "timezone" | "has_logo" | "version">;

export type LaborRate = {
  id: string;
  name: string;
  hourly_price_cents: number;
  is_default: boolean;
  archived_at: string | null;
  version: number;
};

export type LaborRateInput = { name: string; hourly_price_cents: number; is_default?: boolean };

export function settingsApi(workshopId: string) {
  const request = <T>(path: string, method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE", body?: unknown) =>
    apiRequest<T>(path, { method, body, workshopId });
  return {
    get: () => request<WorkshopSettings>("/workshop/settings", "GET"),
    update: (settings: WorkshopSettings, changes: Partial<WorkshopSettingsInput>) =>
      request<void>("/workshop/settings", "PATCH", { version: settings.version, ...changes }),
    logo: () => apiBlob("/workshop/settings/logo", { workshopId }),
    uploadLogo: (file: File) => request<void>("/workshop/settings/logo", "PUT", file),
    removeLogo: () => request<void>("/workshop/settings/logo", "DELETE"),
    rates: (archived: boolean) =>
      request<LaborRate[]>(`/workshop/labor-rates?archived=${archived}`, "GET"),
    createRate: (input: LaborRateInput) => request<{ id: string }>("/workshop/labor-rates", "POST", input),
    updateRate: (rate: LaborRate, changes: Partial<LaborRateInput>) =>
      request<void>(`/workshop/labor-rates/${rate.id}`, "PATCH", { version: rate.version, ...changes }),
    setArchived: (rate: LaborRate, archived: boolean) =>
      request<void>(`/workshop/labor-rates/${rate.id}/${archived ? "archive" : "unarchive"}`, "POST", {
        version: rate.version,
      }),
  };
}
