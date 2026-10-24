import type { ComponentProps } from "react";

import { Input } from "@/shared/components/ui/input";
import { Label } from "@/shared/components/ui/label";

type FieldProps = ComponentProps<typeof Input> & {
  id: string;
  label: string;
  /** Mensaje de error ya traducido. */
  error?: string;
};

/**
 * Etiqueta + campo + error, ligados con id y aria-describedby para que un lector
 * de pantalla lea el error al llegar al campo (RNF-23).
 */
export function Field({ id, label, error, ...input }: FieldProps) {
  const errorId = `${id}-error`;
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        {...input}
      />
      {error && (
        <p id={errorId} className="text-destructive text-sm">
          {error}
        </p>
      )}
    </div>
  );
}
