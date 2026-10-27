import { Search } from "lucide-react";
import { useId, type ComponentProps } from "react";

import { InputGroup, InputGroupAddon, InputGroupInput } from "@/shared/components/ui/input-group";
import { Switch } from "@/shared/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/shared/components/ui/toggle-group";
import { cn } from "@/shared/lib/utils";

/**
 * Los filtros de los listados, iguales en todos: búsqueda con lupa, opciones de
 * sí o no como interruptor y "cuáles ver" como un control segmentado.
 */

export function SearchInput({ className, ...props }: ComponentProps<typeof InputGroupInput>) {
  return (
    <InputGroup className={cn("max-w-sm", className)}>
      <InputGroupAddon>
        <Search />
      </InputGroupAddon>
      <InputGroupInput type="search" autoComplete="off" {...props} />
    </InputGroup>
  );
}

export function SwitchFilter({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <Switch id={id} checked={checked} onCheckedChange={(value) => onChange(value)} />
      <label htmlFor={id} className="cursor-pointer text-sm">
        {label}
      </label>
    </div>
  );
}

/** Uno de varios, siempre uno elegido: pulsar el activo no lo deja en blanco. */
export function SegmentedFilter<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  /** Para lectores de pantalla: qué se está eligiendo. */
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <ToggleGroup
      aria-label={label}
      variant="outline"
      size="sm"
      spacing={0}
      value={[value]}
      onValueChange={(next: string[]) => {
        if (next[0]) onChange(next[0] as T);
      }}
    >
      {options.map((option) => (
        <ToggleGroupItem
          key={option.value}
          value={option.value}
          className="data-pressed:bg-primary data-pressed:text-primary-foreground px-3"
        >
          {option.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
