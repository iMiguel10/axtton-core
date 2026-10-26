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

export type AdminMe = { actor: "superadmin"; installation_mode: "multi" | "single" };

export const adminApi = {
  me: () => apiRequest<AdminMe>("/admin/me"),
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

export type SuperadminsList = {
  superadmins: { email: string; created_at: string }[];
  pending_invitations: { id: string; email: string; expires_at: string }[];
};

export const superadminsApi = {
  list: () => apiRequest<SuperadminsList>("/admin/superadmins"),
  invite: (email: string) =>
    apiRequest<{ invitation_email_sent: boolean }>("/admin/superadmins/invitations", {
      method: "POST",
      body: { email },
    }),
};
