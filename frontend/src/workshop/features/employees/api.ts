import { apiRequest } from "@/shared/lib/apiClient";

import type { Role } from "../session/api";

export type Employee = {
  id: string;
  name: string;
  position: string | null;
  role: Role;
  active: boolean;
  has_access: boolean;
  invitation_pending: boolean;
  /** Nulo si quien consulta no puede ver costes. */
  hourly_cost_cents: number | null;
  /** Se devuelve al editar: bloqueo optimista (RNF-15). */
  version: number;
};

export type EmployeeInput = {
  name: string;
  position: string | null;
  role: Role;
  hourly_cost_cents: number | null;
};

export type EmployeeChanges = Partial<EmployeeInput & { active: boolean }>;

export function employeesApi(workshopId: string) {
  const request = <T>(path: string, method: "GET" | "POST" | "PATCH", body?: unknown) =>
    apiRequest<T>(`/workshop/employees${path}`, { method, body, workshopId });
  return {
    list: () => request<Employee[]>("", "GET"),
    create: (input: EmployeeInput) => request<{ id: string }>("", "POST", input),
    update: (employee: Employee, changes: EmployeeChanges) =>
      request<void>(`/${employee.id}`, "PATCH", { version: employee.version, ...changes }),
    removeAccess: (employee: Employee) =>
      request<void>(`/${employee.id}/access/remove`, "POST", { version: employee.version }),
    invite: (employee: Employee, email: string) =>
      request<{ invitation_email_queued: boolean }>(`/${employee.id}/invitation`, "POST", {
        email,
      }),
  };
}
