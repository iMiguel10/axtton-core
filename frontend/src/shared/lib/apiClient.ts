/**
 * Único punto de acceso HTTP a la API. Solo los `services/` de cada feature lo
 * importan; los hooks y componentes nunca llaman a fetch directamente.
 *
 * Rutas relativas (/api/v1/...): el navegador nunca cambia de origen (arquitectura
 * §5), así que las cookies de sesión viajan solas.
 *
 * No gestiona el 401: el SDK de SuperTokens intercepta fetch, renueva la sesión y
 * reintenta. Renovar también aquí provocaría renovaciones duplicadas, que
 * SuperTokens interpreta como robo de token y cierra la sesión (trampa heredada de
 * Applications Tracker).
 */

export class ApiError extends Error {
  readonly status: number;
  /** Código estable de la API (p. ej. "last_admin"); se traduce con errors.<code>. */
  readonly code: string | null;

  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  /** Se envía como JSON; un `Blob` (una imagen), tal cual y con su tipo. */
  body?: unknown;
  /** El taller activo: va en X-Workshop-Id y el backend lo valida (A6). */
  workshopId?: string;
};

async function send(
  path: string,
  { method = "GET", body, workshopId }: RequestOptions,
): Promise<Response> {
  const headers: Record<string, string> = {};
  const raw = body instanceof Blob;
  if (raw) headers["Content-Type"] = body.type;
  else if (body !== undefined) headers["Content-Type"] = "application/json";
  if (workshopId) headers["X-Workshop-Id"] = workshopId;

  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    body: raw ? body : body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(response.status, data?.code ?? null, response.statusText);
  }
  return response;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Lo que no es JSON (una imagen). Con `fetch`, porque un `<img src>` no puede
 * llevar la cabecera del taller activo. */
export async function apiBlob(path: string, options: RequestOptions = {}): Promise<Blob> {
  return (await send(path, options)).blob();
}
