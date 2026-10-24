import { apiRequest } from "@/shared/lib/apiClient";

export type AuditEntry = {
  seq: number;
  created_at: string;
  action: string;
  /** Nombre del empleado (taller) o email (plataforma). */
  actor: string | null;
  target_type: string | null;
  target_name: string | null;
  /** {"campo": [antes, después]} o datos de la acción. */
  details: Record<string, unknown>;
};

export type AuditPage = { entries: AuditEntry[]; next_before: number | null };

/** El del taller activo (/workshop) o el de la plataforma (/admin). */
export type AuditScope = { prefix: "/workshop"; workshopId: string } | { prefix: "/admin" };

export function fetchAuditPage(scope: AuditScope, before: number | null) {
  const query = before === null ? "" : `?before=${before}`;
  return apiRequest<AuditPage>(`${scope.prefix}/audit${query}`, {
    workshopId: scope.prefix === "/workshop" ? scope.workshopId : undefined,
  });
}
