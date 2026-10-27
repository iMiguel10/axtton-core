import Session from "supertokens-web-js/recipe/session";

import { clearDrafts } from "./drafts";

export type Actor = "staff" | "superadmin" | "client";

/**
 * El actor de la sesión, leído del token. El navegador puede LEER el contenido del
 * token (no la firma, ni modificarlo sin que el servidor lo rechace, T9): sirve
 * para decidir qué pantallas enseñar, nunca para conceder permisos. Eso lo decide
 * siempre el backend en cada petición.
 */
export async function currentActor(): Promise<Actor | null> {
  if (!(await Session.doesSessionExist())) return null;
  const payload = await Session.getAccessTokenPayloadSecurely();
  return (payload.actor as Actor | undefined) ?? null;
}

export async function signOut(): Promise<void> {
  // Antes de salir, no en el evento SIGN_OUT: la navegación de debajo podría
  // cortar el borrado a medias (arquitectura §12: tablet compartida).
  await clearDrafts();
  await Session.signOut();
  window.location.assign("/login");
}
