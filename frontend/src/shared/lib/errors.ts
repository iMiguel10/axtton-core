import type { TFunction } from "i18next";

import { ApiError } from "./apiClient";

/** Mensaje para la persona: el código estable de la API, traducido (errors.<code>). */
export function errorMessage(t: TFunction, error: unknown): string {
  if (error instanceof ApiError && error.code) {
    return t(`errors.${error.code}`, { defaultValue: t("errors.unknown") });
  }
  // Un 422 sin código es la validación de FastAPI: algún dato no es válido (un
  // email que el backend no acepta, por ejemplo), no un fallo del sistema.
  if (error instanceof ApiError && error.status === 422) {
    return t("errors.invalid_input");
  }
  return t("errors.unknown");
}
