import { useSyncExternalStore } from "react";

function subscribe(callback: () => void) {
  window.addEventListener("online", callback);
  window.addEventListener("offline", callback);
  return () => {
    window.removeEventListener("online", callback);
    window.removeEventListener("offline", callback);
  };
}

/**
 * Si el navegador cree que hay conexión. "Sí" no garantiza llegar al servidor
 * (puede estar caído); "no" sí es seguro. Por eso un envío fallido se marca
 * pendiente por su error, no por este valor.
 */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribe, () => navigator.onLine, () => true);
}
