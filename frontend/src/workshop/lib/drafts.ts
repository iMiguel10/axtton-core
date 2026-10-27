import Session from "supertokens-web-js/recipe/session";

/**
 * Borradores en el dispositivo (A11, RNF-22): lo que alguien está escribiendo en
 * una orden (diagnóstico, nota, trabajo) se guarda en IndexedDB a cada cambio,
 * y sobrevive a perder la conexión, a recargar y a cerrar la pestaña.
 *
 * Son de una persona en un taller: la clave lleva su usuario y el taller, y en
 * una tablet compartida el siguiente no ve los del anterior. Se borran al cerrar
 * sesión; si la sesión caduca, se conservan para quien vuelva a entrar y se
 * borran si entra otra persona (`keepOnlyUser`).
 *
 * Sin IndexedDB (navegación privada en algunos navegadores), todo es un no-op:
 * el formulario funciona igual, solo que sin borrador.
 */

export type DraftKind = "diagnosis" | "note" | "work";

export type DraftScope = { workshopId: string; orderId: string; orderCode: string; kind: DraftKind };

export type Draft<T> = DraftScope & {
  key: string;
  userId: string;
  data: T;
  /** Falló el envío por falta de conexión: se reintenta al volver. */
  pending: boolean;
  updatedAt: number;
};

const DB_NAME = "axtton-drafts";
const STORE = "drafts";

let opening: Promise<IDBDatabase | null> | null = null;

function database(): Promise<IDBDatabase | null> {
  opening ??= new Promise((resolve) => {
    try {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => {
        request.result.createObjectStore(STORE, { keyPath: "key" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return opening;
}

/** Una operación sobre el almacén; con `write`, espera a que se confirme. */
async function run<T>(write: boolean, work: (store: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
  const db = await database();
  if (!db) return undefined;
  return new Promise((resolve) => {
    const tx = db.transaction(STORE, write ? "readwrite" : "readonly");
    const request = work(tx.objectStore(STORE));
    tx.oncomplete = () => resolve(request ? request.result : undefined);
    tx.onerror = () => resolve(undefined);
    tx.onabort = () => resolve(undefined);
  });
}

// Avisa a quien enseña lo pendiente (la cabecera) de que algo ha cambiado.
const changes = new EventTarget();

export function onDraftsChanged(listener: () => void): () => void {
  changes.addEventListener("change", listener);
  return () => changes.removeEventListener("change", listener);
}

function changed() {
  changes.dispatchEvent(new Event("change"));
}

async function currentUserId(): Promise<string | null> {
  try {
    return (await Session.doesSessionExist()) ? await Session.getUserId() : null;
  } catch {
    return null;
  }
}

const keyOf = (userId: string, scope: DraftScope) =>
  [userId, scope.workshopId, scope.orderId, scope.kind].join("|");

export async function loadDraft<T>(scope: DraftScope): Promise<Draft<T> | null> {
  const userId = await currentUserId();
  if (!userId) return null;
  const draft = await run<Draft<T>>(false, (store) => store.get(keyOf(userId, scope)));
  return draft ?? null;
}

export async function saveDraft<T>(scope: DraftScope, data: T, pending: boolean): Promise<void> {
  const userId = await currentUserId();
  if (!userId) return;
  const draft: Draft<T> = { ...scope, key: keyOf(userId, scope), userId, data, pending, updatedAt: Date.now() };
  await run(true, (store) => store.put(draft));
  changed();
}

export async function deleteDraft(scope: DraftScope): Promise<void> {
  const userId = await currentUserId();
  if (!userId) return;
  await run(true, (store) => store.delete(keyOf(userId, scope)));
  changed();
}

/** Los que esperan conexión, de quien tiene la sesión y en este taller. */
export async function pendingDrafts(workshopId: string): Promise<Draft<unknown>[]> {
  const userId = await currentUserId();
  if (!userId) return [];
  const all = (await run<Draft<unknown>[]>(false, (store) => store.getAll())) ?? [];
  return all.filter((d) => d.pending && d.userId === userId && d.workshopId === workshopId);
}

/** Al cerrar sesión: no queda nada de nadie en el dispositivo. */
export async function clearDrafts(): Promise<void> {
  await run(true, (store) => store.clear());
  changed();
}

/** Al iniciar sesión: fuera los borradores de cualquier otra persona. */
export async function keepOnlyUser(userId: string): Promise<void> {
  const all = (await run<Draft<unknown>[]>(false, (store) => store.getAll())) ?? [];
  const others = all.filter((d) => d.userId !== userId);
  if (others.length === 0) return;
  await run(true, (store) => {
    for (const draft of others) store.delete(draft.key);
  });
  changed();
}
