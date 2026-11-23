/**
 * Cantidades: con tres decimales como mucho, porque se venden litros de aceite
 * (numeric(10,3), arquitectura §3). La API las manda como texto ("1.500") para
 * no perder decimales; el navegador no hace cuentas con ellas.
 */

/** "1.500" → "1,5": la cantidad como se escribiría. */
export function formatQuantity(value: string): string {
  return String(Number(value)).replace(".", ",");
}

/** "1,5" → "1.5"; nulo si no es una cantidad positiva con tres decimales como mucho. */
export function parseQuantity(value: string): string | null {
  const normalized = parseQuantityOrZero(value);
  return normalized !== null && Number(normalized) > 0 ? normalized : null;
}

/** Como `parseQuantity`, pero admite el cero (un stock mínimo de 0). */
export function parseQuantityOrZero(value: string): string | null {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d{1,7}(\.\d{1,3})?$/.test(normalized)) return null;
  return normalized;
}
