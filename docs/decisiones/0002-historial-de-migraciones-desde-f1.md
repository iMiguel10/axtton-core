# 0002 — El historial de migraciones empieza de cero en F1

- **Fecha:** 2026-10-24
- **Estado:** aceptada

## Contexto

F0 creó dos migraciones con tablas mínimas y desechables: `workshops`, `clients`, `vehicles` y `work_orders` sin la mayoría de sus columnas, y `quotes` con un enlace secreto (`approval_token_hash`) que en F4 sustituirá el enlace mágico. F1 y F2 rehacen esas tablas casi por completo.

No hay ninguna base de datos con datos que conservar: nada se ha desplegado (el primer despliegue es en F2), y la de desarrollo se recrea con `seed_f0`.

## Decisión

Antes de la primera migración de F1 se **borran las dos migraciones de F0**, y el historial empieza con una migración inicial nueva. Esa migración reescribe, con la misma forma, lo que F0 demostró: la función `app_current_workshops()`, la política común, las FK compuestas y los triggers de inmutabilidad.

En desarrollo hay que recrear la base: `docker compose down -v`.

## Alternativas descartadas

- **Conservar las migraciones de F0 y migrar encima**: el historial empezaría con tablas y columnas que nunca existirán en producción (`approval_token_hash`), y cada migración de F1 sería un `ALTER` sobre un esquema provisional. Es más difícil de leer y no protege ningún dato, porque no lo hay.
- **Editar las migraciones de F0 en el sitio**: mezcla el esqueleto con el diseño definitivo y hace creer que esas migraciones son las originales.

## Consecuencias

- El primer despliegue (F2) parte de un historial limpio.
- **A partir del primer despliegue esto ya no se puede hacer**: una migración aplicada en producción no se borra ni se edita nunca; se corrige con otra.
- El código de F0 que se tira sigue en el historial de git (commits `a8b310d` a `a0a4489`).
