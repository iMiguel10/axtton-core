import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PdfButton } from "@/shared/components/PdfButton";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card";
import { Label } from "@/shared/components/ui/label";

import { useActiveWorkshop } from "../session/ActiveWorkshop";
import { vehiclesApi, type Vehicle } from "./api";

/**
 * El informe de actuaciones del vehículo (RF-18): todas sus órdenes, de todos
 * sus titulares. Suele acabar en manos de quien compra el coche, así que sale
 * sin titulares ni importes; el administrador puede añadirlos, y queda en la
 * auditoría (RNF-16).
 */
export function VehicleReportCard({ vehicle }: { vehicle: Vehicle }) {
  const { t } = useTranslation();
  const { workshopId, canExtendVehicleReport } = useActiveWorkshop();
  const api = vehiclesApi(workshopId);
  const [owners, setOwners] = useState(false);
  const [amounts, setAmounts] = useState(false);
  const plate = vehicle.plate_normalized || "vehiculo";

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("vehicles.report.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-muted-foreground text-sm">{t("vehicles.report.hint")}</p>
        {canExtendVehicleReport && (
          <div className="grid gap-2">
            <Option id="report-owners" checked={owners} onChange={setOwners} label={t("vehicles.report.owners")} />
            <Option id="report-amounts" checked={amounts} onChange={setAmounts} label={t("vehicles.report.amounts")} />
            {(owners || amounts) && (
              <p className="text-muted-foreground text-xs">{t("vehicles.report.audited")}</p>
            )}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <PdfButton
            label={t("vehicles.report.download")}
            filename={`informe-de-actuaciones-${plate}.pdf`}
            load={() => api.reportPdf(vehicle.id, { owners, amounts })}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function Option({
  id,
  checked,
  onChange,
  label,
}: {
  id: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <input
        id={id}
        type="checkbox"
        className="accent-primary size-4"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <Label htmlFor={id}>{label}</Label>
    </div>
  );
}
