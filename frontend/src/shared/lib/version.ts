import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "./apiClient";

/**
 * La versión de esta interfaz y la de la API. Ninguna se escribe a mano: las dos
 * salen de la etiqueta de git y del commit, que la CI pasa al compilar
 * (VITE_APP_VERSION y VITE_APP_COMMIT aquí, APP_VERSION y APP_COMMIT en la API).
 * En desarrollo no hay ninguna: "dev".
 */
export const APP_VERSION = import.meta.env.VITE_APP_VERSION || "dev";
export const APP_COMMIT = import.meta.env.VITE_APP_COMMIT || null;

export type Meta = { version: string; commit: string | null; api: string };

/** "0.3.0 (a1b2c3d)": entre dos versiones, el commit dice qué corre exactamente. */
export function versionLabel(version: string, commit: string | null): string {
  return commit ? `${version} (${commit})` : version;
}

/**
 * La de la API, pública (GET /api/v1/meta). Se vuelve a pedir al volver a la
 * pestaña y cada diez minutos: así se nota un despliegue sin recargar.
 */
export function useServerMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => apiRequest<Meta>("/meta"),
    staleTime: 60_000,
    refetchInterval: 10 * 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  });
}

/**
 * Si la API es de otra versión que esta interfaz, se ha desplegado una nueva y
 * esta pestaña sigue con el código viejo. En desarrollo nunca: no hay versión.
 */
export function isOutdated(server: Meta | undefined): boolean {
  if (!server || server.version === "dev" || APP_VERSION === "dev") return false;
  if (server.version !== APP_VERSION) return true;
  return Boolean(server.commit && APP_COMMIT && server.commit !== APP_COMMIT);
}
