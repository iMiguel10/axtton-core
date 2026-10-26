import { apiRequest } from "@/shared/lib/apiClient";

type VehicleBrief = { id: string; plate: string; make: string | null; model: string | null };

export type SearchResult = {
  /** Con su titular actual: el cliente de la orden que se abra. */
  vehicles: (VehicleBrief & { owner: { id: string; name: string } | null })[];
  /** Con los vehículos de los que es titular hoy. */
  clients: { id: string; name: string; phone: string; archived: boolean; vehicles: VehicleBrief[] }[];
};

/** La búsqueda única del mostrador (RF-14): matrícula, nombre o teléfono. */
export const search = (workshopId: string, q: string) =>
  apiRequest<SearchResult>(`/workshop/search?${new URLSearchParams({ q })}`, { workshopId });
