import { apiRequest } from "@/shared/lib/apiClient";

export const FUELS = [
  "gasoline",
  "diesel",
  "hybrid",
  "plug_in_hybrid",
  "electric",
  "lpg",
  "cng",
  "other",
] as const;
export type Fuel = (typeof FUELS)[number];

export type Owner = { id: string; name: string };

export type Vehicle = {
  id: string;
  plate: string;
  plate_normalized: string;
  vin: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  fuel: Fuel | null;
  next_itv_date: string | null;
  next_service_date: string | null;
  next_service_km: number | null;
  /** El titular actual: el periodo abierto de su titularidad. */
  owner: Owner | null;
  /** Se devuelve al editar o cambiar el titular: bloqueo optimista (RNF-15). */
  version: number;
};

export type Ownership = { client: Owner; started_at: string; ended_at: string | null };

export type VehicleDetail = Vehicle & { owner: Owner; ownerships: Ownership[] };

export type VehicleInput = {
  plate: string;
  vin: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  fuel: Fuel | null;
  next_itv_date: string | null;
  next_service_date: string | null;
  next_service_km: number | null;
};

export const PAGE_SIZE = 50;

export function vehiclesApi(workshopId: string) {
  const request = <T>(path: string, method: "GET" | "POST" | "PATCH", body?: unknown) =>
    apiRequest<T>(`/workshop/vehicles${path}`, { method, body, workshopId });
  return {
    list: ({ q, ownerId }: { q?: string; ownerId?: string }, offset = 0) => {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      if (q?.trim()) params.set("q", q.trim());
      if (ownerId) params.set("owner_id", ownerId);
      return request<Vehicle[]>(`?${params}`, "GET");
    },
    get: (id: string) => request<VehicleDetail>(`/${id}`, "GET"),
    create: (input: VehicleInput, ownerId: string) =>
      request<{ id: string }>("", "POST", { ...input, owner_id: ownerId }),
    update: (vehicle: Vehicle, changes: Partial<VehicleInput>) =>
      request<void>(`/${vehicle.id}`, "PATCH", { version: vehicle.version, ...changes }),
    changeOwner: (vehicle: Vehicle, clientId: string) =>
      request<void>(`/${vehicle.id}/owner`, "POST", {
        version: vehicle.version,
        client_id: clientId,
      }),
    suggestions: (field: "make" | "model", q: string, make?: string) => {
      const params = new URLSearchParams({ field, q });
      if (make) params.set("make", make);
      return request<string[]>(`/suggestions?${params}`, "GET");
    },
  };
}
