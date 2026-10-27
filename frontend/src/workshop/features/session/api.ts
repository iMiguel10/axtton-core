import { apiRequest } from "@/shared/lib/apiClient";

export type Role = "admin" | "mechanic";

/** `timezone`: IANA ("Europe/Madrid"); las fechas se enseñan en la del taller. */
export type Membership = { workshop_id: string; workshop_name: string; timezone: string; role: Role };
type StaffMe = { actor: "staff"; workshops: Membership[] };
type ActiveWorkshop = { workshop_id: string; employee_id: string; role: Role };

export const fetchMe = () => apiRequest<StaffMe>("/workshop/me");

/** El backend valida el taller de la cabecera; si ya no trabajo en él, 404. */
export const fetchActive = (workshopId: string) =>
  apiRequest<ActiveWorkshop>("/workshop/active", { workshopId });
