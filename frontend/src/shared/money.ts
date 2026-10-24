const euros = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });

/**
 * 10346 → "103,46 €". La API manda céntimos enteros y el navegador solo los pinta:
 * nunca hace cuentas con importes (los totales los calcula y guarda el backend).
 */
export function formatEur(cents: number): string {
  return euros.format(cents / 100);
}

/** "85,50" o "85.50" → 8550. Lo que escribe el usuario, pasado a céntimos. */
export function parseEurToCents(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) {
    return null;
  }
  const [whole, decimals = ""] = normalized.split(".");
  return Number(whole) * 100 + Number(decimals.padEnd(2, "0"));
}
