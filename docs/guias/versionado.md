# Versionado

La versión de AXTTON CORE es **la última etiqueta de git `vX.Y.Z`**. No se escribe a mano en ningún fichero: la CI la lee y la pasa a la API y al frontend al construirlos ([decisión 0003](../decisiones/0003-versionado-por-etiquetas-y-release-please.md)).

## Dónde se ve

- **`GET /api/v1/meta`**, pública: `{"version": "0.3.0", "commit": "a1b2c3d", "api": "v1"}`. La misma versión sale en el OpenAPI (`/docs`).
- **En la interfaz:** al pie del menú de la cuenta (la de la interfaz) y en Mi cuenta (la de la interfaz y la del servidor).
- **Al desplegar:** si la API ya es de otra versión que la pestaña abierta, la interfaz avisa bajo la cabecera y ofrece recargar. No recarga sola: podría haber un formulario a medias.

En desarrollo no hay versión: las dos dicen `dev` y el aviso nunca sale.

Entre dos versiones publicadas, lo que se construye lleva la última etiqueta y su commit: `0.2.0 (a5a5df4)` es "lo que había en `main` en `a5a5df4`, después de la 0.2.0".

## El número

Versionado semántico, en `0.x` mientras ningún taller lo use de verdad:

| Commit | Qué sube |
|---|---|
| `fix: …` | el parche (`0.3.0` → `0.3.1`) |
| `feat: …` | la menor (`0.3.0` → `0.4.0`) |
| `feat!: …` o `BREAKING CHANGE:` | también la menor mientras sea `0.x`; la mayor desde `1.0.0` |
| `docs:`, `test:`, `refactor:`, `ci:`, `chore:` | nada, y no salen en el registro |

En la práctica, una versión menor por fase: `v0.1.0` cerró F0, `v0.2.0` F1, y `v0.3.0` cerrará F2.

**El contrato de la API (`/api/v1`) no cambia con cada versión**, solo ante un cambio incompatible para quien la usa.

## Los commits

[Commits convencionales](https://www.conventionalcommits.org/es/): el tipo y el ámbito en inglés, la descripción en español, citando fase, paso y requisitos cuando aporten.

```text
feat(orders): cobro de una orden cerrada (F2 paso 8, RF-28)
fix(drafts): el reenvío no duplica la nota
docs: guía de versionado
```

## Publicar una versión

1. Cada push a `main` pone al día el PR de versión que mantiene release-please (`chore(main): release 0.3.0`), con el `CHANGELOG.md` y el número propuesto. Es un acumulador: no publica nada.
2. Al cerrar la fase, se revisa ese PR y se fusiona. release-please crea la etiqueta `v0.3.0` y la release de GitHub con las notas.
3. El siguiente despliegue ya responde `0.3.0` en `/api/v1/meta`.

El PR de versión necesita el secreto **`RELEASE_PLEASE_TOKEN`** (un token personal con permiso sobre el contenido y los PR del repositorio): con el token por defecto, GitHub no lanza la CI sobre él.

## Probarlo en local

```bash
.github/scripts/version.sh
```

Imprime `APP_VERSION` y `APP_COMMIT` como los calcula la CI. Para levantar la API con ellos:

```bash
APP_VERSION=0.2.0 APP_COMMIT=$(git rev-parse --short HEAD) docker compose up -d --build api
```
