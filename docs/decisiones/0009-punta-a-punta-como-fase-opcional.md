# 0009 — La prueba de punta a punta, una fase opcional al final

- **Fecha:** 2026-11-23
- **Estado:** aceptada. Cambia la arquitectura §10 ("Punta a punta… CI desde F6") y §11 (F6)

## Contexto

La arquitectura planificaba una prueba de punta a punta con Playwright en la CI desde F6. Esa prueba recorre en un navegador de verdad el flujo de los criterios de éxito: recepción con la hoja firmada, presupuesto, aprobación en el portal y entrega con su resumen. Al planificar F6 era su paso 7. Pasados los seis primeros, el usuario decidió no hacerla en F6.

## Decisión

**La prueba de punta a punta con Playwright sale de F6 y queda como fase opcional al final del proyecto, después de F9** (decidido por el usuario). F6 se queda en ocho pasos, con la demo como paso 7 y el cierre como paso 8.

## Alternativas descartadas

- **Mantenerla como paso 7 de F6**, como estaba planificado.
- **Dejarla para el final de F6, justo antes del cierre**: el cierre de F6 la incluiría, y v0.7.0 también.

## Consecuencias

- **Hasta esa fase, el flujo completo se comprueba de otras formas:**
  - las pruebas de la API, que recorren cada paso por HTTP con la base de datos y los roles reales;
  - el navegador, a mano, en cada paso;
  - qa-verifier, que lo recorre al cerrar cada fase.

  Lo que ninguna de ellas vigila es la interfaz como conjunto: un cambio que rompa una pantalla sin romper la API no hace fallar la CI.
- **El primer criterio de éxito de la especificación (§14)**, el flujo completo funcionando en producción con la demo, se comprueba a mano al cerrar cada fase hasta entonces.
