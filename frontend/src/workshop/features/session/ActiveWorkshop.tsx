import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AppSplash } from "@/shared/components/Loading";
import { Brand } from "@/shared/components/Brand";
import { Button } from "@/shared/components/ui/button";
import { TimeZoneProvider } from "@/shared/lib/dates";
import { errorMessage } from "@/shared/lib/errors";

import { signOut } from "../../lib/session";
import { fetchActive, fetchMe, type Membership, type Role } from "./api";

const STORAGE_KEY = "activeWorkshopId";

type ActiveWorkshopValue = {
  workshopId: string;
  workshopName: string;
  role: Role;
  /** Mi ficha en este taller: quién hizo un trabajo, por defecto. */
  employeeId: string;
  /** Solo para enseñar u ocultar pantallas: el backend vuelve a comprobarlo. */
  canManageEmployees: boolean;
  canViewAudit: boolean;
  canManageClients: boolean;
  canManageOrders: boolean;
  /** Datos del taller, logotipo y tarifas (RF-02): solo el administrador. */
  canManageSettings: boolean;
  workshops: Membership[];
  select: (workshopId: string) => void;
};

const ActiveWorkshopContext = createContext<ActiveWorkshopValue | null>(null);

export function useActiveWorkshop(): ActiveWorkshopValue {
  const value = useContext(ActiveWorkshopContext);
  if (!value) throw new Error("useActiveWorkshop fuera de ActiveWorkshopProvider");
  return value;
}

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/**
 * El taller activo (A6, RF-08). Se recuerda en este navegador, pero lo guardado
 * es solo una preferencia: si ya no trabajo allí, no está en /me y se ignora; y
 * aunque alguien lo manipule, el backend valida X-Workshop-Id en cada petición.
 */
export function ActiveWorkshopProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<string | null>(readStored);
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe });

  const workshops = me.data?.workshops ?? [];
  // Con un solo taller no hay nada que elegir.
  const workshopId =
    workshops.find((w) => w.workshop_id === chosen)?.workshop_id ??
    (workshops.length === 1 ? workshops[0].workshop_id : null);

  const active = useQuery({
    queryKey: ["active", workshopId],
    queryFn: () => fetchActive(workshopId!),
    enabled: workshopId !== null,
  });

  function select(id: string) {
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* sin almacenamiento: se elige de nuevo al recargar */
    }
    // Lo cacheado pertenece al taller anterior: fuera, salvo la lista de talleres.
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" && q.queryKey[0] !== "actor" });
    setChosen(id);
  }

  if (me.isPending || active.isLoading) {
    return <AppSplash />;
  }
  if (me.isError || active.isError) {
    return (
      <CenteredMessage>{errorMessage(t, me.error ?? active.error)}</CenteredMessage>
    );
  }
  if (workshops.length === 0) {
    return <CenteredMessage>{t("workshop.noWorkshops")}</CenteredMessage>;
  }
  if (workshopId === null || !active.data) {
    return <WorkshopSelector workshops={workshops} onSelect={select} />;
  }

  const membership = workshops.find((w) => w.workshop_id === workshopId)!;
  const value: ActiveWorkshopValue = {
    workshopId,
    workshopName: membership.workshop_name,
    role: active.data.role,
    employeeId: active.data.employee_id,
    canManageEmployees: active.data.role === "admin",
    canViewAudit: active.data.role === "admin",
    // El mecánico ve los clientes, pero no los crea ni los edita (especificación §3).
    canManageClients: active.data.role === "admin",
    // El mecánico ve todas las órdenes; abrirlas y editar su recepción, no.
    canManageOrders: active.data.role === "admin",
    canManageSettings: active.data.role === "admin",
    workshops,
    select,
  };
  return (
    <ActiveWorkshopContext value={value}>
      {/* Todas las fechas de debajo, en la zona de este taller (shared/lib/dates). */}
      <TimeZoneProvider timeZone={membership.timezone}>{children}</TimeZoneProvider>
    </ActiveWorkshopContext>
  );
}

function CenteredMessage({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <main className="mx-auto grid max-w-md gap-4 p-6 pt-24">
      <Brand className="h-9" />
      <p role="alert">{children}</p>
      <Button variant="outline" onClick={() => void signOut()}>
        {t("nav.signOut")}
      </Button>
    </main>
  );
}

function WorkshopSelector({
  workshops,
  onSelect,
}: {
  workshops: Membership[];
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <main className="mx-auto grid max-w-md gap-4 p-6 pt-24">
      <Brand className="h-9" />
      <h1 className="text-2xl font-semibold">{t("workshop.chooseTitle")}</h1>
      <ul className="grid gap-2">
        {workshops.map((w) => (
          <li key={w.workshop_id}>
            <Button
              variant="outline"
              className="h-auto w-full justify-between py-3"
              onClick={() => onSelect(w.workshop_id)}
            >
              <span>{w.workshop_name}</span>
              <span className="text-muted-foreground text-xs">{t(`roles.${w.role}`)}</span>
            </Button>
          </li>
        ))}
      </ul>
    </main>
  );
}
