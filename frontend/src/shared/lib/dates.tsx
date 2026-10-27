import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * Las fechas, siempre en la zona del taller (`workshops.timezone`), no en la del
 * navegador: un mecánico de viaje, o un portátil mal configurado, verían si no
 * otra hora de entrega (convenciones de la arquitectura, §3). Sin taller (el
 * superadministrador), la del navegador.
 *
 * Tres clases de fecha:
 * - un instante (`created_at`, `expected_delivery_at`): se pasa a la zona;
 * - un día del calendario (`worked_on`, `paid_on`, "2026-10-27"): no tiene zona,
 *   se enseña tal cual (formatearlo como instante podría moverlo de día);
 * - lo relativo ("hace 3 días"), con el instante exacto al pasar el ratón.
 */

const TimeZoneContext = createContext<string | undefined>(undefined);

export function TimeZoneProvider({ timeZone, children }: { timeZone: string; children: ReactNode }) {
  return <TimeZoneContext.Provider value={timeZone}>{children}</TimeZoneContext.Provider>;
}

/** Las partes de un instante en una zona: año, mes, día, hora y minuto. */
function zonedParts(date: Date, timeZone: string | undefined) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return {
    year: get("year"),
    month: get("month"),
    day: get("day"),
    hour: get("hour"),
    minute: get("minute"),
    second: get("second"),
  };
}

/** Cuánto adelanta la zona a UTC en ese instante (cambia con el horario de verano). */
function offsetMs(date: Date, timeZone: string | undefined): number {
  const p = zonedParts(date, timeZone);
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - date.getTime();
}

const pad = (n: number) => String(n).padStart(2, "0");

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 86_400_000],
  ["month", 30 * 86_400_000],
  ["week", 7 * 86_400_000],
  ["day", 86_400_000],
  ["hour", 3_600_000],
  ["minute", 60_000],
];

export function useDates() {
  const { i18n } = useTranslation();
  const timeZone = useContext(TimeZoneContext);
  const language = i18n.language;
  return useMemo(() => {
    const dateTimeFormat = new Intl.DateTimeFormat(language, { timeZone, dateStyle: "short", timeStyle: "short" });
    const dateFormat = new Intl.DateTimeFormat(language, { timeZone, dateStyle: "medium" });
    const longFormat = new Intl.DateTimeFormat(language, { timeZone, dateStyle: "full", timeStyle: "short" });
    const dayFormat = new Intl.DateTimeFormat(language, { timeZone: "UTC", dateStyle: "medium" });
    const relativeFormat = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
    return {
      timeZone,
      /** "27/10/26, 13:00": un instante, en la zona del taller. */
      dateTime: (iso: string | null) => (iso ? dateTimeFormat.format(new Date(iso)) : null),
      /** "27 oct 2026": el día de un instante, en la zona del taller. */
      date: (iso: string | null) => (iso ? dateFormat.format(new Date(iso)) : null),
      /** "lunes, 27 de octubre de 2026, 13:00": para el título al pasar el ratón. */
      long: (iso: string) => longFormat.format(new Date(iso)),
      /** "27 oct 2026": un día del calendario ("2026-10-27"), sin moverlo de zona. */
      day: (ymd: string | null) => (ymd ? dayFormat.format(new Date(`${ymd}T00:00:00Z`)) : null),
      /** "hace 3 días", "mañana", "dentro de 2 horas". */
      relative: (iso: string, now: number) => {
        const diff = new Date(iso).getTime() - now;
        const [unit, size] = UNITS.find(([, ms]) => Math.abs(diff) >= ms) ?? ["minute", 60_000];
        return relativeFormat.format(Math.round(diff / size), unit);
      },
      /** Un instante como valor de un <input type="datetime-local">, en la zona del taller. */
      toInput: (iso: string | null) => {
        if (!iso) return "";
        const p = zonedParts(new Date(iso), timeZone);
        return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
      },
      /**
       * Lo escrito en un <input type="datetime-local"> (hora del taller) como
       * instante ISO. Se tantea con la diferencia de la zona y se corrige una vez,
       * por si el instante cae al otro lado de un cambio de hora.
       */
      fromInput: (value: string) => {
        const [date, time] = value.split("T");
        const [y, m, d] = date.split("-").map(Number);
        const [hh, mm] = time.split(":").map(Number);
        const asUtc = Date.UTC(y, m - 1, d, hh, mm);
        let instant = asUtc - offsetMs(new Date(asUtc), timeZone);
        instant = asUtc - offsetMs(new Date(instant), timeZone);
        return new Date(instant).toISOString();
      },
    };
  }, [language, timeZone]);
}
