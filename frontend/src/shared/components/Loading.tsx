import { useTranslation } from "react-i18next";

import { Brand } from "@/shared/components/Brand";
import { Card, CardContent, CardHeader } from "@/shared/components/ui/card";
import { Skeleton } from "@/shared/components/ui/skeleton";

/**
 * Lo que se ve mientras se carga, con la forma de lo que va a llegar: así la
 * pantalla no salta al pintarse, y se entiende qué viene. Un "Cargando…" en texto
 * solo queda para lectores de pantalla (`role="status"`).
 */

function LoadingLabel() {
  const { t } = useTranslation();
  return <span className="sr-only">{t("common.loading")}</span>;
}

/** Al arrancar la aplicación, antes de saber quién ha entrado: la marca. */
export function AppSplash() {
  return (
    <div role="status" className="bg-background flex min-h-svh flex-col items-center justify-center gap-6">
      <Brand className="h-12 motion-safe:animate-pulse" />
      <span aria-hidden className="bg-muted relative h-1 w-40 overflow-hidden rounded-full">
        <span className="bg-ring absolute inset-y-0 left-0 w-1/3 rounded-full motion-safe:animate-[loading-bar_1.2s_ease-in-out_infinite]" />
      </span>
      <LoadingLabel />
    </div>
  );
}

/** Las filas de una tabla mientras llegan. */
export function TableSkeleton({ rows = 6, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div role="status" className="grid gap-3">
      <div className="flex gap-4 border-b pb-3">
        {Array.from({ length: columns }, (_, i) => (
          <Skeleton key={i} className="h-4 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex gap-4">
          {Array.from({ length: columns }, (_, i) => (
            <Skeleton key={i} className={i === 0 ? "h-5 w-28" : "h-5 flex-1"} />
          ))}
        </div>
      ))}
      <LoadingLabel />
    </div>
  );
}

/** Una ficha: el título y unas cuantas tarjetas. */
export function DetailSkeleton({ cards = 3 }: { cards?: number }) {
  return (
    <div role="status" className="grid gap-4">
      <Skeleton className="h-8 w-56" />
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: cards }, (_, i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-5 w-32" />
            </CardHeader>
            <CardContent className="grid gap-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-2/3" />
            </CardContent>
          </Card>
        ))}
      </div>
      <LoadingLabel />
    </div>
  );
}

/** Unas líneas dentro de una tarjeta que ya está pintada. */
export function LinesSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div role="status" className="grid gap-2">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={i % 2 ? "h-4 w-1/2" : "h-4 w-3/4"} />
      ))}
      <LoadingLabel />
    </div>
  );
}
