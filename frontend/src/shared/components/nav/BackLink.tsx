import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { buttonVariants } from "@/shared/components/ui/button";
import { cn } from "@/shared/lib/utils";

/** "Volver al listado", con aspecto de botón: se ve y se pulsa bien en el móvil. */
export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2 self-start justify-self-start")}>
      <ArrowLeft />
      {children}
    </Link>
  );
}
