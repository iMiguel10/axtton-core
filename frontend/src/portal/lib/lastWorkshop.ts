/**
 * El último taller por el que se entró en este navegador. Es solo una comodidad:
 * cuando la sesión caduca o se cierra, se vuelve a la entrada de ese taller en vez
 * de a una página sin taller. No es un dato de nadie: el id del taller está en la
 * dirección que el propio taller reparte.
 */
const KEY = "axtton.portal.lastWorkshop";

export function rememberWorkshop(workshopId: string): void {
  try {
    localStorage.setItem(KEY, workshopId);
  } catch {
    // Almacenamiento bloqueado o en modo privado: se vuelve a /portal/login.
  }
}

/** La entrada a la que volver: la del último taller, o la página sin taller. */
export function loginPath(): string {
  try {
    const workshopId = localStorage.getItem(KEY);
    if (workshopId) return `/portal/login/${encodeURIComponent(workshopId)}`;
  } catch {
    // Igual que arriba.
  }
  return "/portal/login";
}
