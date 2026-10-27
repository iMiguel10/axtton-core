import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/shared/lib/apiClient";
import { useOnline } from "@/shared/lib/useOnline";

import { deleteDraft, loadDraft, saveDraft, type DraftScope } from "./drafts";

/** El envío no llegó al servidor: `fetch` falla sin respuesta (sin conexión). */
export function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

/**
 * Para lo que lleva el id del borrador (notas y trabajos): un 409
 * `already_saved` dice que lo ya enviado llegó, aunque se perdiera la respuesta.
 */
export async function unlessAlreadySaved(request: Promise<unknown>): Promise<void> {
  try {
    await request;
  } catch (error) {
    if (!(error instanceof ApiError && error.code === "already_saved")) throw error;
  }
}

export function newDraftId(): string {
  return crypto.randomUUID();
}

type Options<T> = {
  /** Lo que había guardado al abrir la pantalla: el componente lo vuelve a poner. */
  onRestore: (data: T) => void;
  /** Reenvía lo pendiente; se llama al volver la conexión. */
  resend: (data: T) => void;
};

/**
 * El borrador de un formulario de la orden (RNF-22). El formulario sigue
 * teniendo su propio estado; esto lo copia al dispositivo (`save` a cada
 * cambio), lo devuelve al volver (`onRestore`) y lo borra al enviarse bien
 * (`discard`). Si el envío falla por falta de conexión, `failed` lo marca
 * pendiente y se reenvía solo en cuanto vuelve, con la pantalla abierta, o al
 * volver a abrirla.
 */
export function useDraft<T>(scope: DraftScope, { onRestore, resend }: Options<T>) {
  const { workshopId, orderId, orderCode, kind } = scope;
  const [pending, setPending] = useState(false);
  const [restored, setRestored] = useState(false);
  const data = useRef<T | null>(null);
  const callbacks = useRef({ onRestore, resend });
  useEffect(() => {
    callbacks.current = { onRestore, resend };
  });

  useEffect(() => {
    let ignore = false;
    void loadDraft<T>({ workshopId, orderId, orderCode, kind }).then((draft) => {
      if (ignore || !draft) return;
      data.current = draft.data;
      callbacks.current.onRestore(draft.data);
      setRestored(true);
      setPending(draft.pending);
    });
    return () => {
      ignore = true;
    };
  }, [workshopId, orderId, orderCode, kind]);

  // Un reintento por cada vez que vuelve la conexión (y uno al abrir): si el
  // navegador cree que hay conexión pero el servidor no responde, reintentar a
  // cada fallo sería un bucle. Ahí queda el botón.
  const online = useOnline();
  const retried = useRef(false);
  useEffect(() => {
    if (!online) retried.current = false;
    if (online && pending && !retried.current && data.current !== null) {
      retried.current = true;
      callbacks.current.resend(data.current);
    }
  }, [online, pending]);

  const scopeOf = useCallback(
    (): DraftScope => ({ workshopId, orderId, orderCode, kind }),
    [workshopId, orderId, orderCode, kind],
  );

  return {
    /** Lo escrito no se ha podido enviar y espera a la conexión. */
    pending,
    /** Lo que hay en el formulario viene de un borrador anterior. */
    restored,
    save: useCallback(
      (next: T) => {
        data.current = next;
        setPending(false);
        void saveDraft(scopeOf(), next, false);
      },
      [scopeOf],
    ),
    discard: useCallback(() => {
      data.current = null;
      setPending(false);
      setRestored(false);
      void deleteDraft(scopeOf());
    }, [scopeOf]),
    /** Tras un envío fallido: pendiente si fue la conexión; si no, sigue como borrador. */
    failed: useCallback(
      (next: T, error: unknown) => {
        data.current = next;
        const offline = isNetworkError(error);
        setPending(offline);
        void saveDraft(scopeOf(), next, offline);
      },
      [scopeOf],
    ),
  };
}
