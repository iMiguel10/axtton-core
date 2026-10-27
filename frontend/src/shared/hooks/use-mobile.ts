import * as React from "react"

const MOBILE_BREAKPOINT = 768
const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

function subscribe(callback: () => void) {
  const mql = window.matchMedia(QUERY)
  mql.addEventListener("change", callback)
  return () => mql.removeEventListener("change", callback)
}

/**
 * Si la pantalla es de móvil (la barra lateral pasa a panel). El de shadcn lo
 * calculaba con un setState dentro de un efecto, que la regla de lint del
 * proyecto no admite; useSyncExternalStore es la forma de leer algo de fuera de
 * React, como useOnline.
 */
export function useIsMobile() {
  return React.useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => false
  )
}
