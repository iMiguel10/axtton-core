# Cierre de F0: lo aprendido

> Fase cerrada el 2026-10-24. Commits `a8b310d` a `a0a4489`.

F0 era un **esqueleto vertical desechable**: un único camino de punta a punta, feo y sin adornos, para descubrir dónde están las dificultades reales antes de construir encima (especificación §11).

El camino que se construyó:

1. Un taller abre una orden.
2. Crea un presupuesto de una línea y lo envía.
3. El cliente lo aprueba desde un enlace secreto en el móvil.
4. La orden cambia de estado.
5. Los dos descargan el mismo PDF.

Todo ello con RLS de verdad, triggers de inmutabilidad y 36 pruebas.

## Lo que se confirmó

Partes del diseño que funcionaron como se esperaba y que ahora están demostradas con pruebas, no solo escritas:

| Idea del diseño | Cómo se comprobó |
|---|---|
| RLS falla cerrado: sin taller fijado no se ve **ninguna** fila | R1, con el rol de la aplicación y también con el dueño de las tablas |
| `FORCE ROW LEVEL SECURITY` hace que el dueño también obedezca | R1 del dueño: sin `FORCE`, vería todo |
| El taller fijado no se queda pegado a la conexión del pool | R7. Se rompió a propósito (`set_config(..., false)`) y la prueba falló, que es lo que debía hacer |
| Las FK compuestas impiden mezclar talleres aunque se salte RLS | Prueba con el rol de plataforma |
| Un presupuesto enviado no se puede tocar ni por SQL | Triggers probados con el rol de plataforma; `UPDATE` y `DELETE` de decisiones rechazados por permisos (R5) |
| Una tabla nueva sin RLS se detecta sola | R4 recorre el catálogo de Postgres |
| WeasyPrint genera la misma salida para la misma entrada | El PDF del taller y el del portal son idénticos byte a byte |
| Las dos aplicaciones de frontend no comparten código propio | Al compilar: portal 2,2 KB, taller 2,8 KB, y React y `shared/` en un paquete común. La regla de ESLint salta con un import cruzado |

## Lo que se descubrió

Cosas que el diseño no había previsto o había previsto mal. Cada una ya está corregida en el documento correspondiente.

| Descubrimiento | Por qué importa | Dónde ha quedado |
|---|---|---|
| **Los roles no se pueden crear en una migración**: solo un superusuario crea un rol con `BYPASSRLS` | El diseño decía lo contrario | [Decisión 0001](../decisiones/0001-roles-solo-en-el-script-de-inicio.md) |
| **Vaciar tablas solo lo puede hacer el dueño**: nadie tiene `DELETE` sobre las tablas append-only, ni siquiera el rol de plataforma | Las pruebas y los datos de desarrollo necesitan una vía propia (`TRUNCATE` con el dueño), que la aplicación nunca puede usar | CLAUDE.md, trampas |
| **El orden de escritura choca con los triggers**: al enviar, los totales de las líneas tienen que escribirse antes de marcar el presupuesto como enviado | En el orden inverso, el propio trigger de inmutabilidad rechaza la escritura | CLAUDE.md, trampas |
| **Sin `FOR UPDATE`, la base de datos protege los datos pero el usuario recibe un 500** | El trigger es la red de seguridad; el bloqueo es lo que da un 409 limpio. Hacen falta los dos | CLAUDE.md, trampas |
| **El servicio necesita el id del taller, no solo la sesión**: la política `WITH CHECK` exige que cada fila nueva lleve su `workshop_id` | La dependencia del taller devuelve un contexto (taller + sesión), no una sesión suelta | El patrón que hereda F1 |
| **Los enlaces para el cliente apuntan al frontend, no a la API** | La API necesita saber dónde vive el frontend (`APP_URL`) | [Arquitectura](index.md), §9 |
| **El portal necesita su propio *fallback***: con dos aplicaciones, "cualquier ruta desconocida sirve `index.html`" carga la aplicación equivocada | En desarrollo lo resuelve un plugin de Vite; **en producción, el proxy debe enviar `/portal/*` a `portal/index.html`** | [Arquitectura](index.md), §9 |
| **Un PDF que exige cabeceras no se puede abrir con un enlace normal** | En F0 se descarga con `fetch`. Con la sesión por cookie de F1 deja de hacer falta | Se resuelve en F1 |
| **El PDF cambia cuando el cliente decide**, porque muestra el estado | "Idéntico" quiere decir idéntico **para el mismo estado** | [Especificación](../producto/especificacion.md), RF-55 |
| **La imagen slim de Python no trae ninguna tipografía** | Sin fuentes, el PDF sale con cuadrados | Dockerfile; en F3 las fuentes viajan con la plantilla |
| **Cargar datos a mano en un `useEffect` exige protegerse de respuestas obsoletas** | El plugin de React lo marca como error | Confirma que TanStack Query entra en F1 |
| **Windows**: los ficheros montados en Docker parecen ejecutables, no llegan avisos de cambios y los `.sh` necesitan LF | Ruff ignora `EXE002`, Vite usa *polling* y `.gitattributes` fuerza LF | Ya configurado |

## Qué se queda y qué se tira

| | Pieza | Qué pasa con ella |
|---|---|---|
| **Se queda** | `compose.yml`, los Dockerfiles, `entrypoint.sh` | Se amplían con SuperTokens, Valkey y Mailpit en F1 |
| | `deploy/postgres/initdb/01-roles.sh` | Tal cual |
| | Configuración de Alembic (`alembic.ini`, `env.py`, plantilla) | Tal cual |
| | `core/config.py`, `core/db.py` (`set_workshops`, `workshop_transaction`), `core/errors.py` y su traducción en `main.py` | Tal cual |
| | `platform/db.py` | Tal cual |
| | `infra/pdf.py` (hilo aparte, semáforo, *fetcher* sin recursos externos) | Tal cual |
| | `domain/quotes.py` (redondeo) y `domain/money.py` | Se amplían en F3 con descuentos y desglose de IVA |
| | El patrón de RLS (`app_current_workshops`, la política común, las FK compuestas) y los triggers de inmutabilidad | Se reescriben en la migración inicial de F1 (decisión 0002) con la misma forma |
| | Las pruebas de RLS (R1–R4, R7), las de inmutabilidad, la de concurrencia, el `conftest.py` y `reset_data.py` | Se adaptan a las tablas definitivas |
| | Configuración del frontend (`vite.config.ts` con las dos entradas, el proxy y `portalFallback`; ESLint con la regla de separación; los `tsconfig`) | Tal cual; F1 añade Tailwind, shadcn, i18n y TanStack Query |
| | `shared/api.ts`, `shared/money.ts` | Se adaptan a TanStack Query |
| **Se tira** | Las dos migraciones de F0 | El historial de migraciones se reinicia en F1 (decisión 0002) |
| | Los repositorios con SQL escrito a mano | Se sustituyen por modelos de SQLAlchemy |
| | El taller por cabecera **sin comprobar** | La cabecera `X-Workshop-Id` se queda (A6), pero validada contra los empleados de la sesión |
| | El portal por enlace secreto sin sesión y la columna `approval_token_hash` | En F4, enlace mágico y sesión de cliente |
| | `seed_f0.py` | Datos de demostración de verdad en F9 |
| | `WorkshopApp.tsx`, `PortalApp.tsx` y `styles.css` | Pantallas reales, con diseño y la guía de marca |
| | Los estados de la orden escritos a mano en el presupuesto | Ciclo de vida completo con historial en F2 |

## Riesgos que F0 ha reducido y los que siguen abiertos

- **Reducidos:** el patrón multi-taller con RLS, la inmutabilidad en la base de datos, el PDF en el servidor y las dos aplicaciones de frontend. Ya no son supuestos; están construidos y probados.
- **Sigue abierto, y es el siguiente riesgo grande:** personalizar la receta passwordless de SuperTokens para ligar el enlace mágico a un taller (riesgos de la arquitectura, §12). F0 no lo tocó a propósito: era una fase sin autenticación. Se prueba al principio de F4.
