import type { TFunction } from "i18next";

/**
 * El nombre de un cliente para enseñarlo. Uno anonimizado (RF-15) lo tiene
 * vacío, y es el único caso posible: el formulario y la API exigen nombre. Sus
 * órdenes, vehículos y entradas de auditoría siguen apuntando a él.
 */
export function clientName(t: TFunction, name: string | null | undefined): string {
  return name || t("clients.deleted");
}
