import { useEffect, useState } from "react";

/** El valor, pero solo cuando lleva `delayMs` sin cambiar: una búsqueda por
 * palabra escrita, no por tecla. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
