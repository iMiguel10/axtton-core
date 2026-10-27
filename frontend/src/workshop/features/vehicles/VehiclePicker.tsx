import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/shared/components/ui/button";
import { Input } from "@/shared/components/ui/input";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

import { clientName } from "../clients/clientName";
import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { vehiclesApi, type Vehicle } from "./api";

/**
 * Elegir un vehículo escribiendo su matrícula (como se escriba: "1234-bcd"
 * encuentra "1234 BCD"), su VIN, su marca o su modelo. Enseña su titular, que
 * será el cliente de la orden.
 */
export function VehiclePicker({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: Vehicle | null;
  onChange: (vehicle: Vehicle | null) => void;
}) {
  const { t } = useTranslation();
  const { workshopId } = useActiveWorkshop();
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search).trim();
  const results = useQuery({
    queryKey: ["vehicles", workshopId, { q }, "picker"],
    queryFn: () => vehiclesApi(workshopId).list({ q }),
    enabled: value === null && q.length > 0,
  });

  if (value) {
    return (
      <div className="grid gap-1.5">
        <span className="text-sm font-medium">{label}</span>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono font-medium">{value.plate}</span>
          <span className="text-muted-foreground text-sm">
            {[value.make, value.model].filter(Boolean).join(" ")}
          </span>
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)}>
            {t("vehicles.pickAnother")}
          </Button>
        </div>
      </div>
    );
  }

  const options = (results.data ?? []).slice(0, 6);
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        type="search"
        autoComplete="off"
        placeholder={t("vehicles.searchPlaceholder")}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {q && results.isSuccess && (
        <ul className="grid gap-1" aria-label={t("vehicles.pickResults")}>
          {options.length === 0 ? (
            <li className="text-muted-foreground text-sm">{t("vehicles.noResults")}</li>
          ) : (
            options.map((vehicle) => (
              <li key={vehicle.id}>
                <Button
                  type="button"
                  variant="outline"
                  className="h-auto w-full justify-between py-1.5"
                  onClick={() => {
                    onChange(vehicle);
                    setSearch("");
                  }}
                >
                  <span className="font-mono">{vehicle.plate}</span>
                  <span className="text-muted-foreground text-xs">
                    {vehicle.owner ? clientName(t, vehicle.owner.name) : "—"}
                  </span>
                </Button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
