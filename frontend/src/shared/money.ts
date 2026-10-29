const euros = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });

/**
 * 10346 → "103,46 €". La API manda céntimos enteros y el navegador solo los pinta:
 * nunca hace cuentas con importes (los totales los calcula y guarda el backend).
 */
export function formatEur(cents: number): string {
  return euros.format(cents / 100);
}

/** 8550 → "85,50": un importe para volver a ponerlo en un campo de texto. */
export function centsToInput(cents: number): string {
  return (cents / 100).toFixed(2).replace(".", ",");
}

/** 2100 → "21 %". Los porcentajes viajan en puntos básicos (convenciones §3). */
export function formatPercentBp(bp: number): string {
  return `${(bp / 100).toLocaleString("es-ES", { maximumFractionDigits: 2 })} %`;
}

/** 2100 → "21"; 1050 → "10,5": un porcentaje para volver a ponerlo en un campo. */
export function bpToInput(bp: number): string {
  return String(bp / 100).replace(".", ",");
}

/** "21" o "10,5" → 2100 o 1050. Hasta dos decimales, entre 0 y 100. */
export function parsePercentToBp(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d{1,3}(\.\d{1,2})?$/.test(normalized)) return null;
  const [whole, decimals = ""] = normalized.split(".");
  const bp = Number(whole) * 100 + Number(decimals.padEnd(2, "0"));
  return bp <= 10_000 ? bp : null;
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
