import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/shared/components/ui/button";
import { Input } from "@/shared/components/ui/input";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { clientsApi } from "./api";

export type PickedClient = { id: string; name: string };

/**
 * Elegir un cliente del taller escribiendo parte de su nombre, teléfono o email.
 * Solo ofrece clientes sin archivar: un archivado no puede recibir un vehículo.
 */
export function ClientPicker({
  id,
  label,
  value,
  onChange,
  exclude,
}: {
  id: string;
  label: string;
  value: PickedClient | null;
  onChange: (client: PickedClient | null) => void;
  /** Un cliente que no tiene sentido ofrecer (el titular actual). */
  exclude?: string;
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search).trim();
  const results = useQuery({
    queryKey: ["clients", workshopId, { q, archived: false }, "picker"],
    queryFn: () => clientsApi(workshopId).list({ q, archived: false }, 0),
    enabled: value === null && q.length > 0,
  });

  if (value) {
    return (
      <div className="grid gap-1.5">
        <span className="text-sm font-medium">{label}</span>
        <div className="flex items-center gap-2">
          <span className="font-medium">{value.name}</span>
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)}>
            {t("clients.pickAnother")}
          </Button>
        </div>
      </div>
    );
  }

  const options = (results.data ?? []).filter((c) => c.id !== exclude).slice(0, 6);
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        type="search"
        autoComplete="off"
        placeholder={t("clients.searchPlaceholder")}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {q && results.isSuccess && (
        <ul className="grid gap-1" aria-label={t("clients.pickResults")}>
          {options.length === 0 ? (
            <li className="text-muted-foreground text-sm">{t("clients.noResults")}</li>
          ) : (
            options.map((client) => (
              <li key={client.id}>
                <Button
                  type="button"
                  variant="outline"
                  className="h-auto w-full justify-between py-1.5"
                  onClick={() => {
                    onChange({ id: client.id, name: client.name });
                    setSearch("");
                  }}
                >
                  <span>{client.name}</span>
                  <span className="text-muted-foreground text-xs">{client.phone}</span>
                </Button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
