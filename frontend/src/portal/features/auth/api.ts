import { apiRequest } from "@/shared/lib/apiClient";

export type PortalMe = {
  actor: "client";
  workshop_id: string;
  workshop_name: string;
  timezone: string;
  client_name: string;
  language: "es" | "en";
};

export type PortalEntry = { workshop_name: string; has_logo: boolean };

/** El taller de una página de entrada (sin sesión). 404 si no existe o está desactivado. */
export function fetchEntry(workshopId: string): Promise<PortalEntry> {
  return apiRequest(`/portal/workshops/${encodeURIComponent(workshopId)}`);
}

/** El taller de /portal/{nombre} (decisión 0007): solo su id. */
export function fetchWorkshopBySlug(slug: string): Promise<{ workshop_id: string }> {
  return apiRequest(`/portal/workshops/by-slug/${encodeURIComponent(slug)}`);
}

/** El logotipo de la entrada: un enlace normal, es público como el nombre. */
export function logoUrl(workshopId: string): string {
  return `/api/v1/portal/workshops/${encodeURIComponent(workshopId)}/logo`;
}

/** Responde siempre lo mismo, exista o no el cliente en ese taller (RF-41). */
export function requestLink(workshopId: string, email: string): Promise<void> {
  return apiRequest("/portal/auth/request-link", {
    method: "POST",
    body: { workshop_id: workshopId, email },
  });
}

/** Cambia el enlace por una sesión: las cookies las pone la respuesta. */
export function consumeLink(workshopId: string, token: string): Promise<void> {
  return apiRequest("/portal/auth/consume", {
    method: "POST",
    body: { workshop_id: workshopId, token },
  });
}

export function fetchMe(): Promise<PortalMe> {
  return apiRequest("/portal/me");
}
