/**
 * La orden a la que lleva el botón de un aviso (F5 paso 5). El correo apunta a la
 * entrada del taller con `?order=<id>`: con sesión de ese taller se va directo a
 * ella; sin sesión, se recuerda aquí y, al entrar con el enlace mágico, se lleva a
 * ella en vez de al inicio.
 *
 * Solo se acepta un id con forma de UUID, y solo se construye una ruta interna
 * con él: no sirve para redirigir a otra parte. Si la orden no es de quien entra,
 * el portal da el mismo "no encontrada" de siempre (T4).
 */
const KEY = "axtton.portal.nextOrder";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** El id de la orden del enlace, si tiene forma de id; si no, nada. */
export function orderFromLink(value: string | null): string | null {
  return value && UUID.test(value) ? value.toLowerCase() : null;
}

export function orderPath(orderId: string): string {
  return `/orders/${orderId}`;
}

export function rememberNextOrder(workshopId: string, orderId: string): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ workshopId, orderId }));
  } catch {
    // Almacenamiento bloqueado: al entrar se irá al inicio, como antes.
  }
}

/**
 * Adónde ir al entrar en un taller: su orden pendiente, si la había (y se olvida),
 * o el inicio. La de otro taller se descarta: no es de esta sesión.
 */
export function takeNextPath(workshopId: string): string {
  try {
    const raw = localStorage.getItem(KEY);
    localStorage.removeItem(KEY);
    if (!raw) return "/";
    const saved = JSON.parse(raw) as { workshopId?: unknown; orderId?: unknown };
    const orderId = typeof saved.orderId === "string" ? orderFromLink(saved.orderId) : null;
    if (saved.workshopId === workshopId && orderId) return orderPath(orderId);
  } catch {
    // Almacenamiento bloqueado o un valor que no es JSON: al inicio.
  }
  return "/";
}
