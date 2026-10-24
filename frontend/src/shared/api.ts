/**
 * Cliente mínimo de la API, compartido por las dos aplicaciones.
 *
 * Las rutas son relativas (/api/...): en desarrollo las reenvía el proxy de Vite
 * y en producción el del servidor, así que el navegador nunca cambia de origen.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(`${status} ${code}`);
    this.status = status;
    this.code = code;
  }
}

/** Texto que se enseña de un error: el código de la API, o el mensaje si no lo hay. */
export function errorText(error: unknown): string {
  return error instanceof ApiError ? error.code : String(error);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    // La API devuelve {"code": "..."} en sus errores (app/main.py).
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.code ?? response.statusText);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** Abre un PDF que exige cabeceras: un <a href> no puede enviarlas. */
export async function openPdf(path: string, headers: HeadersInit): Promise<void> {
  const response = await fetch(path, { headers });
  if (!response.ok) {
    throw new ApiError(response.status, response.statusText);
  }
  const url = URL.createObjectURL(await response.blob());
  window.open(url, "_blank", "noopener");
  // El navegador ya ha abierto la pestaña; se libera la memoria del blob después.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
