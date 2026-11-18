import SignaturePadLib from "signature_pad";
import { useEffect, useImperativeHandle, useRef, type Ref } from "react";

import type { ScreenSignature } from "./api";

export type SignaturePadHandle = {
  clear: () => void;
  /** Los trazos en el marco del lienzo, o null si no se ha firmado. */
  read: () => ScreenSignature | null;
};

/**
 * El lienzo donde firma el cliente (RF-52), con `signature_pad`. Lo que sale son
 * los trazos como números, en píxeles CSS del lienzo: el servidor los comprueba
 * y escribe él el SVG del PDF (arquitectura §7.3). Nunca se manda una imagen.
 */
export function SignaturePad({
  ref,
  label,
  onChange,
}: {
  ref: Ref<SignaturePadHandle>;
  label: string;
  onChange: (empty: boolean) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const pad = useRef<SignaturePadLib | null>(null);
  // La última versión de onChange, sin volver a crear el lienzo al cambiar.
  const changed = useRef(onChange);
  useEffect(() => {
    changed.current = onChange;
  });

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const instance = new SignaturePadLib(element, { penColor: "#111", minWidth: 1, maxWidth: 3 });
    pad.current = instance;
    // Nítido en pantallas de alta densidad: el lienzo en píxeles reales y el
    // dibujo en píxeles CSS, que son los que dan los puntos. Al cambiar de tamaño
    // (girar la tablet) se borra: los trazos ya no caben en el marco nuevo.
    const resize = () => {
      const ratio = Math.max(window.devicePixelRatio || 1, 1);
      element.width = element.offsetWidth * ratio;
      element.height = element.offsetHeight * ratio;
      element.getContext("2d")?.scale(ratio, ratio);
      instance.clear();
      changed.current(true);
    };
    resize();
    const onEnd = () => changed.current(instance.isEmpty());
    instance.addEventListener("endStroke", onEnd);
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      instance.removeEventListener("endStroke", onEnd);
      instance.off();
      pad.current = null;
    };
  }, []);

  useImperativeHandle(ref, () => ({
    clear: () => {
      pad.current?.clear();
      changed.current(true);
    },
    read: () => {
      const instance = pad.current;
      const element = canvas.current;
      if (!instance || !element || instance.isEmpty()) return null;
      const width = element.offsetWidth;
      const height = element.offsetHeight;
      // Un trazo que se sale un poco del borde se queda en él: el servidor
      // rechaza los puntos fuera del lienzo.
      const inside = (value: number, max: number) => Math.min(Math.max(value, 0), max);
      return {
        width,
        height,
        strokes: instance
          .toData()
          .map((group) => group.points.map((p) => [inside(p.x, width), inside(p.y, height)]))
          .filter((stroke) => stroke.length > 0),
      };
    },
  }));

  return (
    <canvas
      ref={canvas}
      aria-label={label}
      // Blanco también en modo oscuro: es papel, y la tinta es oscura.
      className="h-48 w-full touch-none rounded-md border bg-white sm:h-56"
    />
  );
}
