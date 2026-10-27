import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

/**
 * La última miga de la cabecera (Órdenes › OT-2026-0012). La pone la página que la
 * conoce, una ficha o un alta, con `usePageCrumb`; sin ella, la cabecera muestra
 * solo el apartado y es el título de la página.
 *
 * `asTitle`: la miga es además el `h1` de la página. Para las altas ("Nuevo
 * cliente"), que no tienen nada más que poner de título; una ficha lleva su
 * propio `h1`, con el estado o las etiquetas al lado.
 */

export type PageCrumb = { label: string; asTitle: boolean };

const SetCrumb = createContext<(crumb: PageCrumb | null) => void>(() => undefined);
const Crumb = createContext<PageCrumb | null>(null);

export function PageCrumbProvider({ children }: { children: ReactNode }) {
  const [crumb, setCrumb] = useState<PageCrumb | null>(null);
  return (
    <SetCrumb value={setCrumb}>
      <Crumb value={crumb}>{children}</Crumb>
    </SetCrumb>
  );
}

export function useCurrentCrumb(): PageCrumb | null {
  return useContext(Crumb);
}

/** Desde una página: su nombre en las migas mientras está montada. */
export function usePageCrumb(label: string | null | undefined, asTitle = false): void {
  const set = useContext(SetCrumb);
  useEffect(() => {
    set(label ? { label, asTitle } : null);
    return () => set(null);
  }, [label, asTitle, set]);
}
