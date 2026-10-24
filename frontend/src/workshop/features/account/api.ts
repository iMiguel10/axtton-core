import { apiRequest } from "@/shared/lib/apiClient";

/** La cuenta vive en /workshop/account y en /admin/account: cada prefijo exige su actor. */
export type AccountPrefix = "/workshop" | "/admin";

export type SessionInfo = { created_at: string; current: boolean };

export function accountApi(prefix: AccountPrefix) {
  return {
    changePassword: (current_password: string, new_password: string) =>
      apiRequest<void>(`${prefix}/account/password`, {
        method: "POST",
        body: { current_password, new_password },
      }),
    sessions: () => apiRequest<SessionInfo[]>(`${prefix}/account/sessions`),
    revokeOthers: () =>
      apiRequest<void>(`${prefix}/account/sessions/revoke-others`, { method: "POST" }),
  };
}
