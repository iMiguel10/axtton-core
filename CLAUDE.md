# CLAUDE.md

Guía de trabajo para Claude Code (y cualquier colaborador) en **AXTTON CORE**.

## 1. Qué es

Sistema de gestión para talleres mecánicos: clientes, vehículos, citas, órdenes de trabajo, presupuestos, inventario básico y documentos generados, con un **portal privado** donde el cliente sigue la reparación y aprueba el presupuesto. Una instalación sirve a muchos talleres (multi-taller) o a uno solo. Es un proyecto de portfolio serio, hermano de Applications Tracker, del que hereda stack y convenciones.

> **Estado (2026-10-26): F2 en curso, pasos 1 a 8 de 11 hechos.** Cobro y anonimización (paso 8, migración `0009payment`): el cobro de una orden cerrada (pendiente, cobrada o sin cargo; forma, importe y fecha solo si está cobrada, con dos CHECK), corregible y auditado, y el listado de entregadas pendientes (`/orders/unpaid`, RF-29); anonimizar a un cliente (RF-15) vacía sus datos personales y los de quien trajo el coche, lo archiva, lo congela con un trigger y no se puede con órdenes abiertas; en la interfaz sale como "Cliente eliminado" (`clientName`). Borradores (paso 7, RNF-22): el diagnóstico, la nota y el trabajo que se están escribiendo se guardan en IndexedDB por usuario, taller y orden (`workshop/lib/drafts.ts`, `useDraft.ts`); lo que no se pudo enviar por la conexión queda pendiente y se reenvía al volver, la cabecera avisa sin conexión y enlaza lo pendiente, y al cerrar sesión no queda ninguno. La nota y el trabajo llevan el id del borrador, para que reenviarlos no duplique. Búsqueda única (paso 6, migración `0008search`): `GET /workshop/search` busca a la vez por matrícula, nombre (sin tildes, con `search_text()`) y teléfono (sus dígitos), y el inicio es el mostrador con esa caja y las órdenes abiertas. Diagnóstico, notas y trabajos (paso 5, migración `0007worklog`): el diagnóstico se versiona (append-only, con el índice único como bloqueo optimista), las notas son un hilo append-only y los trabajos se anulan en vez de borrarse; "mis órdenes" incluye aquellas en las que he trabajado, cancelar exige no tener trabajos, y `GET /workshop/staff` da el directorio del personal. Ciclo de vida (paso 4): transiciones manuales en `domain/work_orders.py` con quién hace cada una, cambio de estado con la orden bloqueada, "sin presupuesto" auditado (RF-27), deshacer el último cambio manual (§6, auditado) y la tarjeta de estado en la ficha de la orden. Órdenes (migración `0006orders`): `work_orders`, `work_order_counters` (número por taller y año del taller) y `work_order_status_changes` (append-only, con `opened` como primer cambio), con un trigger diferido que vigila el invariante 5; abrir con el titular del momento, listado con filtros y "mis órdenes", editar la recepción y el responsable; pantallas en `/orders` y las órdenes en las fichas de vehículo y cliente. Los cambios de estado, en el paso 4. Clientes: tabla `clients` con RLS y sin `DELETE` para `axtton_app` (migración `0004clients`), email único por taller, alta, edición con bloqueo optimista, archivo y pantallas en `/clients`. Vehículos y titularidad (migración `0005vehicles`): `vehicles` con matrícula normalizada y VIN únicos por taller, sugerencias de marca y modelo; `vehicle_ownerships` con índice parcial, `EXCLUDE` (`btree_gist`) y un trigger que congela los periodos cerrados; el cambio de titular, auditado; pantallas en `/vehicles` y los vehículos en la ficha del cliente. **F1 hecha y cerrada ([lo aprendido](docs/arquitectura/f1-cierre.md)).** F0 también está cerrada ([lo aprendido](docs/arquitectura/f0-cierre.md)) y su código desechable retirado. Existen `db` con los tres roles, `api` con la migración inicial definitiva (`users`, `workshops`, `employees`, `invitations`, `audit_log`, con RLS y modelos de SQLAlchemy) y la de `superadmin_invitations` y pruebas de RLS; SuperTokens con inicio de sesión del personal y del superadministrador, el actor en la sesión y los tres prefijos de API cerrados entre sí; el comando que crea el superadministrador y, en `/admin`, el alta de talleres con invitación al primer administrador, el listado con recuentos, la desactivación y los límites; la aceptación de invitaciones (ruta pública `/api/v1/invitations`), el taller activo validado en cada petición, el selector de talleres y la gestión de empleados y roles con la matriz de permisos; recuperar y cambiar la contraseña y gestionar sesiones; Mailpit; CI en GitHub Actions; y en el `frontend` (Tailwind + shadcn con la paleta de marca, i18n es/en, TanStack Query) las pantallas de acceso, invitación, selector de taller, empleados, mi cuenta y talleres del superadministrador; el límite de peticiones (RNF-06) con Valkey (arquitectura §2); y la consulta del registro de auditoría (RNF-16), del taller para su administrador y de la plataforma para el superadministrador; e invitar a otros superadministradores desde la aplicación (RF-110, ruta pública `/api/v1/superadmin-invitations`).

## 2. Documentación

Sitio MkDocs en `docs/` (http://localhost:8001). Es la fuente de verdad del diseño; este fichero la resume sin duplicarla.

| Documento | Para qué |
|---|---|
| `docs/producto/especificacion.md` | Requisitos (RF-xx, RNF-xx), roles y matriz de permisos, ciclos de vida, límite conocido, límites, fases, riesgos |
| `docs/arquitectura/index.md` | Decisiones A1–A14 con alternativas descartadas, autenticación de tres actores, modelo de datos, RLS, flujos, segundo plano, entorno, pruebas, orden de implementación y riesgos |
| `docs/decisiones/` | Bitácora de cambios de rumbo durante el desarrollo, con plantilla |
| `docs/arquitectura/f0-cierre.md` | Lo aprendido en F0, y qué del esqueleto se queda y qué se tira |
| `docs/arquitectura/f1-cierre.md` | Lo aprendido en F1: lo confirmado, lo descubierto al cerrarla y lo que queda abierto |
| `docs/guias/demo.md` | Los datos de demostración: cómo se cargan, las cuentas y qué hay |
| `docs/referencia/` | Vacía a propósito hasta que haya código |

**Si el código y un documento no coinciden, no se corrige el documento sin más.** Primero se averigua si el diseño evolucionó (se actualiza el documento dejando constancia) o si la implementación se lo saltó (y entonces es un fallo del código).

## 3. Stack y servicios

Existen `docs`, `db`, `supertokens` + `supertokens-db`, `api`, `valkey`, `mailpit` y `frontend`. El resto es el diseño (arquitectura §9), en la fase en que aparece:

| Servicio | Puerto | Notas | Desde |
|---|---|---|---|
| `docs` | 8001 | MkDocs Material **fijado a la 9** (MkDocs 2.0 rompe plugins y temas) | **existe** |
| `db` | 5432 | **Existe.** Postgres 17 con RLS y tres roles, creados por `deploy/postgres/initdb/01-roles.sh` junto con la base `axtton_test`: `axtton_owner` (migraciones), `axtton_app` (API y worker, sin `BYPASSRLS`), `axtton_platform` (solo `app/platform/`) | F0 |
| `api` | 8000 | **Existe**, con Alembic (aplica las migraciones al arrancar). Diseño completo: FastAPI + SQLAlchemy async + Alembic (Python, uv) + SDK de SuperTokens + WeasyPrint | F0 |
| `frontend` | 5173 | **Existe**, con las pantallas de F1 (el portal es un marcador hasta F4). Vite con dos aplicaciones: `src/workshop/` en `/` y `src/portal/` en `/portal`. React 19 + TS, TanStack Query, react-hook-form + zod, Tailwind v4 + shadcn/ui, i18next (es, en) | F0 |
| `supertokens` + `supertokens-db` | — | **Existe** (core fijado a 12.2.0, SDK a 0.31.3). Receta `emailpassword` (personal y superadministrador); `passwordless` (clientes) llega en F4. Rutas en `/api/auth`, sin registro público | F1 |
| `valkey` | — | **Existe.** Contadores del límite de peticiones (RNF-06); la cola de SAQ llega con el worker en F5. Sin `VALKEY_URL` o con `RATE_LIMIT_ENABLED=false`, no se limita nada | F1 |
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
docker compose exec api python -m app.scripts.create_superadmin <email>   # el primero; pide la contraseña (o SUPERADMIN_PASSWORD). Los demás, por invitación en /admin/superadmins
docker compose exec api python -m app.scripts.seed_demo   # BORRA todo y crea la demo: dos talleres, cuentas y un mes de trabajo (docs/guias/demo.md). Solo con DEMO_SEED_ENABLED=true
# CI: .github/workflows/ci.yml ejecuta en cada push lo mismo que aquí (backend con compose, frontend con npm ci, docs estricto).
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
- **Un email se envía después del commit, nunca dentro de la transacción**: si la transacción fallara, llegaría una invitación a algo que no existe. Desde un endpoint del taller se usa `BackgroundTasks` de FastAPI, que corre después de enviar la respuesta.
- **Una dependencia que hace commit al salir del `yield` va con `Depends(..., scope="function")`** (`ActiveWorkshop`, `InvitationSession`). Con el ámbito por defecto (`"request"`), FastAPI ejecuta esa salida **después** de enviar la respuesta y de las `BackgroundTasks`: el cliente recibía un 2xx de algo aún sin guardar y el email salía antes que su invitación. Lo encontró qa-verifier al cerrar F1 (`tests/test_commit_order.py`); la trampa anterior daba por hecho el orden contrario.
- **Lo que depende de un recuento se pone en fila con `employee_repo.lock_staff`** (bloqueo consultivo por taller, `pg_advisory_xact_lock`): que quede un administrador (RF-05), el límite de empleados con acceso (RF-114), las reinvitaciones. Con READ COMMITTED, dos transacciones cuentan cada una sin ver la otra y las dos pasan. Va al principio del service, antes de leer, y antes que cualquier `FOR UPDATE`, siempre en ese orden (`tests/test_concurrency.py`).
- **Una carrera no se prueba con `asyncio.gather` sobre la API**: el cliente HTTP en memoria acaba atendiendo las dos peticiones una tras otra, y la prueba pasa aunque quites la guarda (le pasó al email único de `clients`). Se intercalan dos transacciones reales a mano, como en `tests/test_concurrency.py`, y se comprueba que la prueba falla sin la guarda.
- **Un índice único es la última palabra, no la comprobación previa**: dos altas a la vez pasan las dos el "¿ya existe?" y la segunda choca con el índice. `services/integrity.py::flush_or_conflict` traduce ese `IntegrityError`, por el nombre de la restricción, al mismo 409 que la comprobación; sin eso, un 500.
- **Cambiar el titular bloquea el vehículo** (`vehicle_repo.get_for_update`, con `populate_existing` para no quedarse con lo leído antes del bloqueo). Sin el bloqueo, dos cambios a la vez cierran el mismo periodo y el segundo choca con el trigger `vehicle_ownerships_closed_frozen`: un 500 en vez de un 409. El fin del periodo viejo y el inicio del nuevo salen de **un solo** `clock_timestamp()` de la base de datos.
- **Postgres comprueba los índices únicos y `EXCLUDE` antes que las FK**: una prueba que quiera ver fallar una FK compuesta tiene que esquivar antes las demás restricciones (en `test_ownerships_db.py`, un periodo antiguo y cerrado).
- **Un permiso por columna obliga a adaptar las pruebas genéricas**: de `vehicle_ownerships`, `axtton_app` solo puede actualizar `ended_at`, así que un `UPDATE … SET created_at = created_at` da `permission denied` aunque no toque ninguna fila. `test_rls_tables.py` usa `UPDATABLE_COLUMN` para esas tablas.
- **El año de una orden es el del taller, no el de UTC**: `order_repo.local_year` lo calcula en la base de datos con `AT TIME ZONE workshops.timezone`. A las 23:30 UTC del 31 de diciembre, en Madrid ya es el año siguiente.
- **Abrir una orden bloquea el vehículo con `FOR SHARE` antes de leer el titular**: la FK de la orden también acaba esperando a un cambio de titular en curso, pero ya con el titular viejo leído.
- **El invariante 5 lo vigila un `CONSTRAINT TRIGGER` diferido**: el error no salta en la sentencia que lo rompe, sino al confirmar. En una prueba, el `pytest.raises` tiene que envolver el `begin()` entero, no solo el `execute`.
- **PL/pgSQL resuelve los campos de `NEW` de toda una expresión, también de la rama que no se ejecuta**: un `CASE` con `NEW.work_order_id` falla en un trigger que también corre sobre `work_orders`. Hay que usar `IF` con asignaciones separadas.
- **Para llevar una orden a un estado en una prueba** (antes de que exista la transición), `force_status` en `test_work_orders.py` escribe con el rol de plataforma el cambio y el estado a la vez, que es lo único que acepta el trigger.
- **Qué transición existe y quién la hace vive en `TRANSITIONS`** (`domain/work_orders.py`), no en los endpoints ni en el frontend. La ficha devuelve `allowed_transitions` para el rol de quien la mira; un botón nuevo en la interfaz es una fila nueva en esa tabla.
- **Un componente con el error de su mutación no lleva `key={version}`**: tras un 409 la recarga trae otra versión, el componente se remonta y el mensaje desaparece antes de poder leerlo (`StatusCard`). Los formularios sí lo llevan, porque su error vive en la página.
- **Bajo RLS, un índice solo sirve para condiciones `LEAKPROOF`**: la igualdad sí (el índice por `workshop_id` funciona), `LIKE` no, así que un índice trigram nunca se usa. Antes de añadir un índice para una consulta del taller, comprueba con `EXPLAIN` como `axtton_app` (no como plataforma ni dueño, que no pasan por RLS igual) y con volumen y `ANALYZE`: con pocas filas el plan no dice nada. `test_search.py` tiene el patrón.
- **Normalizar para buscar se hace en columnas generadas** (`name_search`, `phone_digits`) que calcula Postgres. La consulta normaliza lo escrito con la **misma** función (`search_text()`, que envuelve `unaccent` como IMMUTABLE); si la columna y la consulta normalizaran distinto, "maria" dejaría de encontrar "María" sin que nada fallara.
- **Quien bloquea una fila y luego la actualiza no puede pedir `FOR SHARE`**: dos transacciones así se interbloquean (cada una espera al bloqueo compartido de la otra para actualizar). Registrar un trabajo pide `FOR NO KEY UPDATE` (`order_repo.get_for_activity`); `FOR SHARE` es solo para quien bloquea sin escribir en la fila. Una prueba de concurrencia que quiera ver el interbloqueo tiene que coger los dos bloqueos antes de que ninguno actualice.
- **Un editor de texto largo no se remonta tras un 409**: el del diagnóstico guarda la versión desde la que se editó y, si aparece otra, enseña la del otro y deja elegir (usar la suya, o guardar lo mío encima). Remontarlo con `key` borraría lo escrito (RNF-15).
- **Sin conexión, TanStack Query deja las mutaciones en pausa, no las hace fallar** (`networkMode: "online"`, el valor por defecto): el formulario se quedaría "enviando" y el borrador no sabría que está pendiente. Las de los borradores van con `networkMode: "always"`, y `fetch` falla con un `TypeError` (`isNetworkError`, `errors.network`).
- **Un envío que falló por la conexión pudo llegar igual** (se perdió la respuesta). Lo que se reenvía lleva el id del borrador, y el servidor responde al reenvío como si lo guardara; si lo pendiente se edita, lleva otro id, o el servidor tomaría la versión nueva por un reenvío de la vieja y la descartaría sin avisar.
- **Una ficha con datos no se cambia por el error de recargarla** (`if (!order.data)`, no `if (order.isError)`): sin conexión, la recarga falla y se llevaría por delante los formularios con lo que se está escribiendo.
- **Los borradores se borran antes de `Session.signOut()`**, no en el evento `SIGN_OUT`: después viene la navegación al login, que podría cortar el borrado a medias.
- **Anonimizar y abrir una orden se ponen en fila sobre la fila del cliente** (`client_repo.get_locked`): anonimizar pide `FOR UPDATE` antes de contar sus órdenes abiertas; abrir una orden o darle un vehículo, `FOR SHARE` antes de leerlo. El bloqueo de la FK al insertar la orden también espera, pero llega con el cliente ya leído sin anonimizar.
- **Un cliente anonimizado tiene el nombre vacío, y es lo único que lo distingue en una fila ajena** (la orden, el titular, la auditoría): se enseña siempre con `clientName(t, name)`, que da "Cliente eliminado". Un `{client.name}` suelto deja un hueco en blanco.
- **RNF-40 lo vigila un barrido** (`test_anonymize.py`): todas las tablas convertidas en texto, buscando lo que el cliente era. Una tabla o columna nueva que guarde un dato personal del cliente lo hace fallar, y hay que decidir qué hace con ella la anonimización.
- **Los datos de demo pasan por los services y luego se mueven las fechas** (`app/scripts/seed_demo.py`): así cumplen todas las reglas, y una regla nueva que la demo no cumpla hace fallar `test_seed_demo.py`. Una pantalla o un estado nuevo que se quiera enseñar en la demo se añade ahí. Los periodos de titularidad y los trabajos los congelan triggers con cualquier rol: para moverlos, el dueño desactiva el trigger dentro de su transacción (titularidad) o se fija la fecha al crearlos (`worked_on`).
- **Alembic no detecta los CHECK al generar** una migración: se escriben a mano (`op.create_check_constraint`), y `alembic check` tampoco los echa en falta.
- **En los `details` de la auditoría, cada clave significa una sola cosa**: `status` es el estado de un taller, así que el de una orden va en `work_order_status`. `AuditPage` traduce cada valor según su clave.
- **En el registro de auditoría, un cliente va por id, nunca por nombre**: es append-only y RF-15 obliga a borrar el nombre al anonimizar. El nombre se pone al leerlo (`repositories/audit.py`).
- **`axtton_app` no puede escribir en lo que es de la plataforma** (migración `0003grants`): ni `UPDATE`/`DELETE` en `users` (sin RLS: podría cambiar `kind` a `superadmin`), ni `INSERT`/`UPDATE`/`DELETE` en `workshops`, ni nada en `alembic_version`. Los privilegios por defecto del dueño se lo daban todo; una tabla nueva de plataforma necesita su `REVOKE`.
- **`app.platform` solo se importa desde `/admin`, `/api/v1/superadmin-invitations` (pública, de plataforma), comandos de servidor y las excepciones con nombre de `R8_EXCEPTIONS`** (`tests/test_admin.py`). Añadir una es una decisión de diseño (arquitectura §4), no un arreglo para que pase la prueba. Las capas también se comprueban por imports (`tests/test_architecture.py`): un service que importe `fastapi` o `app.platform` hace fallar la CI.
- **Bloqueo optimista en dos niveles**: el cliente manda la `version` que leyó y el service la compara (409 `modified_by_someone_else`); dentro de la transacción, SQLAlchemy la vigila también, y su `StaleDataError` se traduce al mismo 409 en `main.py`. Para lo que pueden hacer dos personas a la vez sobre la misma fila (aceptar una invitación), además se bloquea con `FOR UPDATE`: el bloqueo da el comportamiento correcto y la versión es la red de seguridad.
- **El rol se comprueba con `require(Action.…)` y `can()`**, nunca comparando `role == "admin"` en un endpoint (RNF-03). El rol sale del taller activo, no de la sesión.
- **Importar `app.main` tiene efectos** (inicializa SuperTokens y fija el emisor de correo). Las pruebas lo importan una vez al principio del `conftest`: importado por primera vez dentro de un fixture, pisaba el emisor de pruebas que otro fixture acababa de poner.
- **SuperTokens enviaría sus emails desde sus servidores** si no se sustituye su servicio de envío. `app/core/auth_emails.py` lo cambia por nuestro `EmailSender` (RF-68), y al completar la recuperación de contraseña cierra todas las sesiones de la cuenta.
- **Para probar que una sesión se cerró, usa su token de renovación**: el de acceso sigue valiendo hasta caducar (5 minutos) porque se valida sin consultar al core.
- **Los `.sh` tienen que ser ejecutables en git, no solo en tu disco**: Windows no tiene ese permiso y git los guarda como `100644`. En local funciona porque Docker Desktop monta los ficheros de Windows como ejecutables; en la CI (Linux) falla con `permission denied`. Un `.sh` nuevo se marca con `git update-index --chmod=+x <fichero>`.
- **En la CI el código montado no es de `appuser`**: el runner es uid 1001 y la API corre como uid 1000, así que no podría crear las cachés de ruff, mypy y pytest. La CI hace `chmod -R a+rwX backend` antes de levantar los servicios.
- **Siempre `localhost`, nunca `127.0.0.1`**: las cookies de sesión no viajan entre los dos.
- **El registro de auditoría de plataforma se filtra por `workshop_id IS NULL` a mano**: `axtton_platform` se salta RLS, así que sin ese filtro el superadministrador vería las acciones de todos los talleres (RNF-08). En el taller lo filtra RLS. Una acción nueva de plataforma se escribe sin `workshop_id`, aunque sea sobre un taller.
- **El límite de las rutas de SuperTokens va en un middleware, no en una dependencia**: SuperTokens las atiende antes que el router. `AuthRateLimitMiddleware` se añade **después** de `get_middleware()` (en Starlette, el último añadido es el más externo); al revés, nunca se ejecutaría. Lee el cuerpo para sacar el email y se lo vuelve a entregar a SuperTokens.
- **Las pruebas corren sin límite de peticiones** (`RATE_LIMIT_ENABLED=false` en `conftest.py`): inician sesión muchas veces desde la misma "IP". `test_rate_limit.py` pone uno real con almacén en memoria.
- **El SDK de SuperTokens del navegador lanza la propia `Response`** ante un HTTP no 2xx (un 429): `signIn` y `sendPasswordResetEmail` van en `try/catch` y `errorMessage` la reconoce.
- **Un `.env` creado antes de un servicio nuevo no tiene sus variables**: al añadir una a `.env.example`, añádela también a tu `.env` (sin `VALKEY_URL`, la API arranca sin límite de peticiones).
- **La caché de TanStack Query se vacía al crear, cerrar o perder la sesión** (`src/workshop/lib/supertokens.ts`). Sin el vaciado al crearla, el "sin sesión" cacheado antes del login devuelve a `/login` justo después de entrar; sin los otros dos, la siguiente persona del navegador vería datos de la anterior.
- **El backend rechaza emails de dominios reservados** como `.local` (422 de validación, sin `code`): para pruebas, `@example.com`. El frontend traduce cualquier 422 sin código como `errors.invalid_input`.
- **`npx shadcn add` se ejecuta dentro del contenedor** (`docker compose exec frontend npx shadcn@latest add …`) y lee los alias de `tsconfig.json` de la raíz: sin sus `paths`, escribía en `frontend/@/`. Después hay que revisar lo que trae: no pisar `button.tsx` ni `input.tsx` (llevan `bg-card` a propósito), traducir sus textos fijos en inglés con `t()` ("Toggle Sidebar", "Close") y pasar el lint (su `use-mobile` llamaba a `setState` dentro de un efecto; ahora usa `useSyncExternalStore`). Si un componente nuevo trae como dependencia otro que ya existe, el CLI pregunta si sobrescribirlo y se para sin terminal: se genera en una carpeta vacía (`--yes --path ./tmp-shadcn`) y se copia solo lo nuevo.
- **La barra lateral marca el apartado por la ruta más larga que lo contiene** (`activeItem` en `AppLayout.tsx`), no con `NavLink end`: así "Clientes" sigue marcado en la ficha de un cliente y `/orders/unpaid` marca "Pendientes de cobro", no "Órdenes".
- **Las piezas comunes de las pantallas ya existen; no se rehacen en cada una:** filtros (`shared/components/filters/Filters.tsx`: búsqueda con lupa, interruptor, control segmentado), filas que llevan a su ficha (`LinkRow`, que respeta los enlaces y botones de dentro y Ctrl+clic), "volver" (`BackLink`), enlaces dentro del texto (la utilidad `link` de `global.css`) y la marca (`Brand` y `BrandMark`, con `tone="onDark"` sobre la barra lateral o el panel de acceso). Además: `ConfirmButton` (nunca `window.confirm`), los skeletons y la pantalla de arranque (`Loading.tsx`), `When` para fechas relativas y `StatusBadge` con un color por estado (tokens `--status-*`). Y: `notify()` para los avisos de "guardado" (`Toaster.tsx`; los errores siguen junto a lo que falló), `EmptyState` para las listas vacías, `MobileCards` para que una tabla sea tarjetas en el móvil, `usePageCrumb` para la miga de la cabecera (una ficha la pone; un listado no repite su `h1`, que lo es la cabecera) y la paleta de Ctrl+K (`CommandPalette.tsx`). Cada pantalla se carga con `lazy()` en `WorkshopApp.tsx`: una nueva, también.
- **Las fechas se formatean con `useDates()` (`shared/lib/dates.tsx`), nunca con `toLocaleString`**: van en la zona del taller, que pone `ActiveWorkshopProvider` desde `/workshop/me`. Un día del calendario (`worked_on`, `paid_on`) se formatea con `day()`, sin pasar por la zona, o podría cambiar de día. El `datetime-local` también se convierte (`toInput` y `fromInput`): el navegador lo interpretaría en su propia zona.
- **Un email nuevo es un `EmailContent` en `domain/emails.py` y se envía con `compose()`** (`infra/email.py`): sale con la plantilla de la marca (`templates/email/base.html`), su texto plano y el logotipo dentro del mensaje (CID). Si es de un taller, su nombre va en la cabecera y en el remitente. Nunca un `Email(body=…)` escrito a mano.
- **Ningún texto de interfaz va escrito a mano en un componente**: todo pasa por `t()` con su clave en `src/shared/i18n/locales/{es,en}.json`, y cada `code` de error de la API tiene su `errors.<code>`.
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
| F1 ✔ | **Hecha** ([cierre](docs/arquitectura/f1-cierre.md)). Autenticación del personal, superadministrador, alta de talleres, modo de instalación, roles, invitaciones, taller activo, auditoría, límite de peticiones, RLS completa con sus pruebas, CI |
| F2 | Clientes, vehículos con titularidad, órdenes con historial, deshacer, búsqueda, borradores, cobro y anonimización. Revisión y validación del diseño de la interfaz **antes** del primer despliegue en Coolify |
| F3 | Datos del taller y tarifas editables por su administrador (RF-02), presupuestos versionados e inmutables, decisión registrada por el taller, PDF con los datos legales |
| F4 | Portal del cliente con enlace mágico por taller y aprobación desde el portal |
| F5 | Worker y bandeja de avisos (presupuesto enviado, vehículo listo) |
| F6 | Hoja de recepción con firma, resumen de entrega, informe de actuaciones |
| F7 | Inventario: catálogo, movimientos de stock, piezas usadas |
| F8 | Citas, recordatorios, vencimientos, borrado de firmas |
| F9 | Resumen entre talleres, exportaciones, demo, copias con restauración probada, rendimiento, manual |
