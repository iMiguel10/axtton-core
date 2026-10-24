# CLAUDE.md

Guía de trabajo para Claude Code (y cualquier colaborador) en **AXTTON CORE**.

## 1. Qué es

Sistema de gestión para talleres mecánicos: clientes, vehículos, citas, órdenes de trabajo, presupuestos, inventario básico y documentos generados, con un **portal privado** donde el cliente sigue la reparación y aprueba el presupuesto. Una instalación sirve a muchos talleres (multi-taller) o a uno solo. Es un proyecto de portfolio serio, hermano de Applications Tracker, del que hereda stack y convenciones.

> **Estado (2026-10-24): F1 en curso, pasos 1 a 3 hechos.** F0 está cerrada ([lo aprendido](docs/arquitectura/f0-cierre.md)) y su código desechable retirado. Existen `db` con los tres roles, `api` con la migración inicial definitiva (`users`, `workshops`, `employees`, `invitations`, `audit_log`, con RLS y modelos de SQLAlchemy) y pruebas de RLS; SuperTokens con inicio de sesión del personal y del superadministrador, el actor en la sesión y los tres prefijos de API cerrados entre sí (`/me` en cada uno); el comando que crea el superadministrador y, en `/admin`, el alta de talleres con invitación por email al primer administrador, el listado con recuentos, la desactivación y los límites; Mailpit; y un `frontend` vacío a la espera del paso 5. Todavía **no se puede aceptar una invitación** (paso 4); lo que este fichero describe de eso es **diseño**.

## 2. Documentación

Sitio MkDocs en `docs/` (http://localhost:8001). Es la fuente de verdad del diseño; este fichero la resume sin duplicarla.

| Documento | Para qué |
|---|---|
| `docs/producto/especificacion.md` | Requisitos (RF-xx, RNF-xx), roles y matriz de permisos, ciclos de vida, límite conocido, límites, fases, riesgos |
| `docs/arquitectura/index.md` | Decisiones A1–A14 con alternativas descartadas, autenticación de tres actores, modelo de datos, RLS, flujos, segundo plano, entorno, pruebas, orden de implementación y riesgos |
| `docs/decisiones/` | Bitácora de cambios de rumbo durante el desarrollo, con plantilla |
| `docs/arquitectura/f0-cierre.md` | Lo aprendido en F0, y qué del esqueleto se queda y qué se tira |
| `docs/guias/`, `docs/referencia/` | Vacías a propósito hasta que haya código |

**Si el código y un documento no coinciden, no se corrige el documento sin más.** Primero se averigua si el diseño evolucionó (se actualiza el documento dejando constancia) o si la implementación se lo saltó (y entonces es un fallo del código).

## 3. Stack y servicios

Existen `docs`, `db`, `supertokens` + `supertokens-db`, `api`, `mailpit` y `frontend`. El resto es el diseño (arquitectura §9), en la fase en que aparece:

| Servicio | Puerto | Notas | Desde |
|---|---|---|---|
| `docs` | 8001 | MkDocs Material **fijado a la 9** (MkDocs 2.0 rompe plugins y temas) | **existe** |
| `db` | 5432 | **Existe.** Postgres 17 con RLS y tres roles, creados por `deploy/postgres/initdb/01-roles.sh` junto con la base `axtton_test`: `axtton_owner` (migraciones), `axtton_app` (API y worker, sin `BYPASSRLS`), `axtton_platform` (solo `app/platform/`) | F0 |
| `api` | 8000 | **Existe**, con Alembic (aplica las migraciones al arrancar). Diseño completo: FastAPI + SQLAlchemy async + Alembic (Python, uv) + SDK de SuperTokens + WeasyPrint | F0 |
| `frontend` | 5173 | **Existe** (F0, sin Tailwind ni i18n todavía). Vite con dos aplicaciones: `src/workshop/` en `/` y `src/portal/` en `/portal`. React 19 + TS, TanStack Query, react-hook-form + zod, Tailwind v4 + shadcn/ui, i18next (es, en) | F0 |
| `supertokens` + `supertokens-db` | — | **Existe** (core fijado a 12.2.0, SDK a 0.31.3). Receta `emailpassword` (personal y superadministrador); `passwordless` (clientes) llega en F4. Rutas en `/api/auth`, sin registro público | F1 |
| `valkey` | — | Cola de SAQ y rate limit | F1 |
| `mailpit` | 8025 | **Existe.** Solo desarrollo: captura todo el correo (http://localhost:8025). Sin `SMTP_HOST`, la aplicación arranca y no envía emails | F1 |
| `worker` | — | Misma imagen que `api`: avisos y tareas programadas | F5 |
| `manual` | 3001 | Docusaurus, manual de producción en es y en | F9 |

## 4. Comandos

```bash
docker compose up docs                       # sitio de documentación en http://localhost:8001
docker compose run --rm docs build --strict  # compila el sitio; falla ante enlaces rotos o avisos

cp .env.example .env                         # primera vez
docker compose up -d --build                 # todo: Postgres, SuperTokens, la API en http://localhost:8000 (/docs = OpenAPI) y el frontend en http://localhost:5173
curl http://localhost:8000/api/health        # {"status":"ok"} si la API llega a la BD
docker compose exec api ruff check .         # estilo
docker compose exec api ruff format .        # formato
docker compose exec api mypy app tests       # tipos
docker compose exec api pytest               # pruebas, contra la base axtton_test con los roles reales
docker compose down -v                       # borra los volúmenes: necesario si cambia deploy/postgres/initdb
docker compose exec api python -m app.scripts.create_superadmin <email>   # pide la contraseña (o SUPERADMIN_PASSWORD); es la única forma de crear uno
docker compose exec api uv add <paquete>     # dependencias: siempre dentro del contenedor, nunca en el host
docker compose exec frontend npx tsc -b        # tipos del frontend
docker compose exec frontend npm run lint     # ESLint, incluida la regla que separa src/workshop y src/portal
docker compose exec frontend npm run build    # compila las dos aplicaciones (dist/index.html y dist/portal/index.html)
docker compose exec frontend npm install <paquete>   # exec, nunca run: con run se instala en otro contenedor
```

**Migraciones:** se cambia el modelo en `app/models/`, se genera con `docker compose exec api alembic revision --autogenerate -m "…"`, **se revisa siempre el fichero generado** y se le añade a mano lo que el generador no sabe (RLS, políticas, triggers, permisos). Se aplican solas al arrancar `api`. La prueba `test_models_match_the_migrations` (`alembic check`) falla si un modelo y las migraciones no coinciden. Los comandos de despliegue se añaden aquí en el mismo commit que los hace existir.

## 5. Estructura y capas

Estructura prevista (arquitectura §6): `backend/app/` con `api/v1/{workshop,portal,admin}/`, `core/`, `domain/`, `models/`, `repositories/`, `schemas/`, `services/`, `platform/`, `infra/`, `jobs/`, `templates/`, `scripts/`; `frontend/src/{workshop,portal,shared}/`.

**Backend:** `endpoints → services → repositories → models`, con `domain/` puro.

| Capa | Puede | No puede |
|---|---|---|
| `api/v1/{workshop,portal,admin}/` | Validar con schemas, `Depends`, llamar a **un** service | Consultar la BD, decidir permisos, `commit`, importar de otro prefijo |
| `services/` | Reglas, `domain/`, repositories, `commit`/`rollback`, escribir en la bandeja de avisos | Importar FastAPI, construir SQL, importar `platform/` |
| `repositories/` | Consultas con la sesión de `axtton_app`, siempre bajo RLS | `commit`, reglas de negocio, usar `axtton_platform` |
| `platform/` | Usar `axtton_platform` y leer varios talleres | Devolver filas operativas al superadministrador; ser importado desde `/workshop` o `/portal` (salvo la petición de enlace mágico) |
| `domain/` | Enums, transiciones, cálculos de totales, días hábiles, matriz de permisos | Cualquier I/O |

**Regla única:** *si habla con la BD, vive en `repositories/`; si decide, en `services/` o `domain/`; si cruza talleres, en `platform/` y en ningún otro sitio.*

**Frontend:** por *features*, una vez en `workshop/` y otra en `portal/`. **`workshop/` y `portal/` no se importan entre sí**; lo común va a `shared/`.

## 6. Convenciones

- **Idioma:** identificadores, tablas, columnas, rutas, cabeceras, carpetas y ficheros de código en inglés (`workshop`, `work_order`, `quote`): "taller" solo aparece en la prosa, nunca en un nombre de código (ni `/taller` ni `X-Taller-Id`); prosa, documentación y commits en español. La interfaz, en español e inglés por i18n desde el primer texto.
- **Modelo de datos** (arquitectura §3): `id uuid`, `created_at` con `clock_timestamp()`, historiales ordenados por `seq` (nunca por fecha), enumerados como `varchar` + `CHECK`, importes en `bigint` de céntimos, IVA en puntos básicos, fechas en `timestamptz` y mostradas en la zona del taller, bloqueo optimista con `version`.
- **Toda tabla de un taller** lleva `workshop_id`, `UNIQUE (id, workshop_id)`, FK compuestas hacia sus padres y la política `workshop_isolation` con RLS forzada.
- **Requisitos citados por número** (RF-xx, RNF-xx, A-xx) en código, commits y pruebas cuando aporten.
- **La documentación cambia en el mismo commit que el código.**

## 7. Invariantes que no se rompen

1. Ninguna consulta de `axtton_app` ve ni escribe filas de un taller distinto del fijado en la transacción; sin taller fijado, no ve ninguna.
2. Solo `app/platform/` usa `axtton_platform`.
3. Cada prefijo de API (`/workshop`, `/portal`, `/admin`) rechaza las sesiones de los otros dos actores, por la dependencia de su router.
4. El actor de una sesión se escribe solo al crearla, en una única función, y no cambia nunca; se lee siempre de la sesión verificada.
5. `work_orders.status` es igual al `to_status` del cambio con el `seq` más alto de su historial.
6. Una versión de presupuesto enviada, una decisión y una hoja de recepción firmada no se modifican jamás; sus totales y su contenido se guardaron al enviar o firmar.
7. El cliente de una orden es el titular del vehículo al abrirla; el portal da acceso por `work_orders.client_id`, nunca por el vehículo.
8. Los avisos se crean en la misma transacción que el cambio que los provoca y no salen dos veces por la misma `dedupe_key`.
9. El stock es la suma de `stock_movements`.

## 8. Trampas conocidas

Ya identificadas en el diseño (arquitectura §2, §3, §4, §8 y §9); se ampliarán con las que aparezcan al construir:

- **RLS no se aplica al dueño de las tablas.** La aplicación se conecta con `axtton_app`, nunca con `axtton_owner`, y las tablas llevan `FORCE ROW LEVEL SECURITY`. Si no, todas las políticas pasan sin que nada falle.
- **El taller se fija con `set_config('app.workshop_ids', …, true)`**: el `true` lo limita a la transacción. Sin él, queda pegado a la conexión del pool y la siguiente petición ve el taller anterior.
- **Revocar las sesiones de un cliente no es `revokeAllSessionsForUser`**: su usuario passwordless es uno por email, compartido entre talleres. Se cierran solo las sesiones con su `workshop_id` y `client_id`.
- **La numeración de órdenes** no sale de una secuencia ni de `MAX + 1`: `work_order_counters` con `INSERT … ON CONFLICT DO UPDATE … RETURNING`.
- **Los scripts de inicio de Postgres solo corren con el volumen vacío.** Los roles se crean solo en `deploy/postgres/initdb/01-roles.sh` (decisión 0001): si lo cambias, `docker compose down -v`.
- **Vaciar tablas solo lo puede hacer el dueño.** Ningún rol de la aplicación tiene `TRUNCATE`, y nadie tiene `DELETE` sobre las tablas append-only (`quote_decisions`). Para pruebas y datos de desarrollo, `app/scripts/reset_data.py` usa `axtton_owner` con `TRUNCATE`, que no dispara triggers de fila ni pasa por RLS.
- **Un presupuesto enviado no se puede tocar ni por SQL**: los triggers `quote_lines_frozen` y `quotes_frozen_after_send` lo rechazan con cualquier rol. Por eso, al enviar, los totales de las líneas se escriben **antes** de marcar el presupuesto como `sent`.
- **Bloquear la orden antes de cambiar su presupuesto** (`SELECT … FOR UPDATE`): sin el bloqueo, dos envíos simultáneos acaban en un 500 al chocar con el trigger; con él, el segundo espera y recibe un 409.
- **WeasyPrint es síncrono y lento**: se ejecuta con `run_in_threadpool` y como mucho dos a la vez (`app/infra/pdf.py`). Llamarlo directamente en un endpoint `async` bloquearía todas las peticiones mientras maqueta. Su fetcher (`NoExternalResources`) no carga nada externo: las plantillas llevan el CSS dentro.
- **La imagen necesita una tipografía** (`fonts-dejavu-core`): la imagen slim de Python no trae ninguna, y sin fuentes el PDF sale con cuadrados.
- **El portal necesita su propio fallback en desarrollo**: Vite sirve `index.html` (el taller) para cualquier ruta desconocida, así que `/portal/quotes/…` cargaría la aplicación equivocada. Lo corrige el plugin `portalFallback` de `vite.config.ts`; en producción, el proxy (F2).
- **Cargar datos en un `useEffect` lleva un indicador `ignore`** que descarta respuestas de una petición ya obsoleta (el taller cambió mientras tanto). Sin él, una respuesta lenta pisa a la buena. TanStack Query lo resolverá desde F1.
- **Docker en Windows no avisa de cambios de fichero**: Vite usa `usePolling` para recargar dentro del contenedor.
- **SQLAlchemy convierte `datetime` en `timestamp` sin zona horaria** salvo que se diga otra cosa. `Base.type_annotation_map` (`app/models/base.py`) lo fija a `timestamptz`; revisando la primera migración generada se vio que faltaba.
- **El registro público se anula en la operación, no en una URL**: SuperTokens atiende el registro en varias rutas (`/api/auth/signup`, `/api/auth/public/signup`…). Una prueba las recorre.
- **Las pruebas usan el core real de SuperTokens**, cuya base de datos no se vacía entre pruebas: cada cuenta de prueba lleva un email único (`make_account` en `conftest.py`).
- **Los engines globales (aplicación y plataforma) se cierran tras cada prueba** en el fixture `client`: sus conexiones quedan ligadas al event loop de la prueba, y la siguiente fallaría con "Event loop is closed".
- **`curl` en Windows estropea las tildes de la línea de comandos**: convierte los argumentos a la codificación antigua de la consola y la API recibe JSON inválido. Para probar a mano con tildes, escribe el cuerpo en un fichero UTF-8 y usa `--data-binary @fichero.json`.
- **Un email se envía después del commit, nunca dentro de la transacción**: si la transacción fallara, llegaría una invitación a algo que no existe.
- **Siempre `localhost`, nunca `127.0.0.1`**: las cookies de sesión no viajan entre los dos.
- Heredadas de Applications Tracker para SAQ y el correo: `retries` cuenta intentos totales, SAQ recuerda la clave de un trabajo unos 10 minutos, el mismo envío puede ejecutarse dos veces a la vez (`FOR UPDATE SKIP LOCKED`), un trabajo nunca lleva un token de acceso, la cola se crea dentro del event loop.

## 9. Agentes

Están en `.claude/agents/`. **No corren solos**: se invocan al cerrar una feature o una fase, con un encargo concreto.

| Agente | Modelo y esfuerzo | Cuándo invocarlo |
|---|---|---|
| `docs-writer` | Sonnet, medio: redactar y contrastar documentos con el código es trabajo de lectura atenta, no de razonamiento profundo | Al cerrar un bloque de trabajo, o cuando el código haya divergido del diseño. No reescribe un documento para que encaje con el código: reporta la divergencia |
| `qa-verifier` | Opus, alto: su valor está en encontrar carreras, fugas entre talleres y pruebas que pasan sin probar nada; fijado para no depender del modelo de la sesión | Antes de dar por terminado un bloque o una fase. Ejecuta, escribe las pruebas que faltan (sobre todo las adversas) y reporta; no arregla el código que evalúa |

## 10. Fases

| Fase | Contenido |
|---|---|
| F0 ✔ | **Hecha** ([cierre](docs/arquitectura/f0-cierre.md)). Esqueleto vertical desechable: orden, presupuesto de una línea, aprobación por enlace secreto, un primer RLS de verdad y un PDF |
| F1 | Autenticación del personal, superadministrador, alta de talleres, modo de instalación, roles, invitaciones, taller activo, auditoría, RLS completa con sus pruebas, CI |
| F2 | Clientes, vehículos con titularidad, órdenes con historial, deshacer, búsqueda, borradores. Primer despliegue en Coolify |
| F3 | Presupuestos versionados e inmutables, decisión registrada por el taller, PDF con los datos legales |
| F4 | Portal del cliente con enlace mágico por taller y aprobación desde el portal |
| F5 | Worker y bandeja de avisos (presupuesto enviado, vehículo listo) |
| F6 | Hoja de recepción con firma, resumen de entrega, informe de actuaciones |
| F7 | Inventario: catálogo, movimientos de stock, piezas usadas |
| F8 | Citas, recordatorios, vencimientos, borrado de firmas |
| F9 | Resumen entre talleres, exportaciones, demo, copias con restauración probada, rendimiento, manual |
