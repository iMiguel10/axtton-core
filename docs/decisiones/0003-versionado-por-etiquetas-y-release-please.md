# 0003 — Versiones por etiqueta de git, con release-please

- **Fecha:** 2026-10-27
- **Estado:** aceptada

## Contexto

Antes del primer despliegue (F2, paso 10) no había forma de saber qué versión corre: `0.1.0` estaba escrito a mano en `main.py`, `pyproject.toml` y `package.json`, nunca se cambió, y no había etiquetas ni registro de cambios. Para quien avisa de un fallo y para comprobar que un despliegue arrancó lo que se acaba de construir hace falta una respuesta fiable. Es el mismo enfoque que Applications Tracker (su issue 18), adaptado a un proyecto que aún no está en producción.

## Decisión

- **La etiqueta de git `vX.Y.Z` es la única fuente de la versión.** La CI la lee (`.github/scripts/version.sh`) y la pasa al construir: `APP_VERSION` y `APP_COMMIT` a la API, `VITE_APP_VERSION` y `VITE_APP_COMMIT` al frontend. `pyproject.toml` y `package.json` se quedan en `0.0.0`.
- **Versionado semántico en `0.x` mientras no lo use un taller real**, con una versión menor por fase cerrada: `v0.1.0` es el cierre de F0, `v0.2.0` el de F1 (etiquetadas hacia atrás) y `v0.3.0` será el de F2. `1.0.0`, cuando un taller pueda usarlo de verdad (portal y presupuestos: F4 como pronto).
- **Commits convencionales desde el paso 9c de F2**, con el tipo en inglés (lo exige la herramienta) y la descripción en español.
- **release-please** mantiene el `CHANGELOG.md` y un PR de versión; fusionarlo crea la etiqueta y la release.
- **El contrato (`/api/v1`) no cambia con cada versión**: solo con un cambio incompatible, marcado como `BREAKING CHANGE`.

## Alternativas descartadas

- **Un `version.txt` o el `package.json` como fuente, editados a mano:** son tres sitios que acaban diciendo cosas distintas, como ya pasaba con el `0.1.0`.
- **Empezar en `1.0.0`, como Applications Tracker:** allí había producción; aquí prometería una estabilidad que no hay.
- **Versión por fecha (`2026.10`):** no dice si un cambio rompe algo, y el contrato de la API lo necesita.
- **Mantener el estilo de commit `F2 paso N: …`:** release-please no sabría qué es una novedad. La fase y el paso se pueden seguir citando en la descripción.
- **Un changelog escrito aparte de los commits:** se olvida. El registro sale de lo que ya se escribe al hacer commit.

## Consecuencias

- `GET /api/v1/meta` responde la versión y el commit, la interfaz la enseña (menú de la cuenta y Mi cuenta) y avisa de recargar cuando la API ya es de otra versión.
- Entre dos versiones, la imagen lleva la última etiqueta y el commit: `0.2.0 (a5a5df4)` dice exactamente qué corre.
- La calidad del changelog depende de los títulos de los commits: un `chore:` que arregla un fallo no sube la versión ni sale en el registro.
- Con el token por defecto de GitHub, la CI no corre sobre el PR de versión: hace falta un token personal en el secreto `RELEASE_PLEASE_TOKEN`.
- Los commits de F2 anteriores a esta decisión no son convencionales: entran en el registro de `0.3.0` como cambios adicionales en el cuerpo del commit del paso 9c, un formato que release-please reconoce.
