import { Toast } from "@base-ui/react/toast";
import { CheckCircle2, X } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * Avisos flotantes: "Guardado", "Cobro registrado", "Orden abierta". Se van solos
 * y no empujan la página. Con el Toast de Base UI (ya instalado): sin dependencia
 * nueva, y los lectores de pantalla los anuncian.
 *
 * Solo para confirmar que algo salió bien. Un error sigue junto a lo que falló
 * (`role="alert"` en su tarjeta): un aviso que se va solo no sirve para explicar
 * qué corregir.
 */
const manager = Toast.createToastManager();

/** "Guardado" y similares, desde cualquier sitio (también fuera de React). */
export function notify(title: string): void {
  manager.add({ title, type: "success", timeout: 3500 });
}

export function Toaster({ children }: { children: ReactNode }) {
  return (
    <Toast.Provider toastManager={manager}>
      {children}
      <Toast.Portal>
        <Toast.Viewport className="fixed right-4 bottom-4 z-[60] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2 outline-none">
          <ToastList />
        </Toast.Viewport>
      </Toast.Portal>
    </Toast.Provider>
  );
}

function ToastList() {
  const { t } = useTranslation();
  const { toasts } = Toast.useToastManager();
  return toasts.map((toast) => (
    <Toast.Root
      key={toast.id}
      toast={toast}
      className="bg-popover text-popover-foreground ring-foreground/10 flex items-center gap-3 rounded-xl p-3 pr-2 shadow-lg ring-1 transition-all duration-200 data-[ending-style]:translate-y-2 data-[ending-style]:opacity-0 data-[starting-style]:translate-y-2 data-[starting-style]:opacity-0"
    >
      <CheckCircle2 className="text-success size-5 shrink-0" />
      <Toast.Title className="flex-1 text-sm font-medium" />
      <Toast.Close
        aria-label={t("common.close")}
        className="text-muted-foreground hover:bg-muted hover:text-foreground rounded-md p-1"
      >
        <X className="size-4" />
      </Toast.Close>
    </Toast.Root>
  ));
}
