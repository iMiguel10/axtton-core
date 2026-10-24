import { apiRequest } from "@/shared/lib/apiClient";

/** Solo datos de cuenta y recuentos: nada operativo del taller (RNF-08). */
export type WorkshopSummary = {
  id: string;
  name: string;
  status: "active" | "inactive";
  created_at: string;
  max_employees_with_access: number;
  employees_with_access: number;
  pending_invitations: number;
};

export type NewWorkshop = { name: string; admin_name: string; admin_email: string };

export const adminApi = {
  list: () => apiRequest<WorkshopSummary[]>("/admin/workshops"),
  create: (input: NewWorkshop) =>
    apiRequest<{ workshop_id: string; invitation_email_sent: boolean }>("/admin/workshops", {
      method: "POST",
      body: input,
    }),
  update: (
    id: string,
    changes: { status?: "active" | "inactive"; max_employees_with_access?: number },
  ) => apiRequest<void>(`/admin/workshops/${id}`, { method: "PATCH", body: changes }),
};
