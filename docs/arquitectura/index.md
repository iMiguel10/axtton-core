# Arquitectura

> Estado: **v0.1** (2026-10-24, puesto al día el 2026-10-28) · F0 y F1 hechas y cerradas ([lo aprendido en F0](f0-cierre.md), [en F1](f1-cierre.md)); F2 construida y desplegada. Donde F1 o F2 resultaron distintas del diseño, el texto lo dice ("al construirlo en F1", "al construirlo en F2").

Este documento recoge **qué se ha decidido y contra qué alternativa**. La especificación de producto está en [producto/especificacion.md](../producto/especificacion.md); los requisitos se citan por su número (RF-xx, RNF-xx).

## 1. Decisiones

| # | Decisión | Elección | Alternativa descartada y por qué |
|---|---|---|---|
| A1 | Backend | **FastAPI + SQLAlchemy async + Alembic**, Python con uv, monolito en capas. Heredado de Applications Tracker | **Cambiar de framework** (Django, NestJS): no hay un requisito que lo pida, y se perderían las convenciones y las trampas ya documentadas. **Microservicios**: un taller no tiene la escala ni el equipo que los justifiquen. |
| A2 | Base de datos | **PostgreSQL 17**, una sola base para la aplicación | Ninguna seria: Postgres además da RLS (A7). |
| A3 | Frontend | **Un proyecto Vite con dos aplicaciones**: `src/workshop/` y `src/portal/`, con lo común en `src/shared/`. React 19 + TS, TanStack Query, react-hook-form + zod, Tailwind v4 + shadcn/ui, i18next. Cada aplicación es una entrada de Vite con su propio paquete | **Una sola SPA con dos árboles de rutas**: el cliente descargaría el código del taller y compartirían estado global. **Dos proyectos**: doble mantenimiento de dependencias y componentes para la misma interfaz. |
| A4 | Autenticación | **SuperTokens para los tres actores**: email y contraseña (receta `emailpassword`) para el personal y el superadministrador; enlace mágico (receta `passwordless`) para los clientes. Detalle en §2 | **Zitadel**: OIDC estándar, passkeys y MFA gratis y consola de identidades, pero **no tiene enlace mágico**: el portal necesitaría un sistema de sesión propio aparte, y en el navegador exige que el backend haga de intermediario para no exponer tokens; además pesa más en infraestructura. Gana en lo que aquí está pospuesto. **Revisar esta decisión si** las apps móviles pasan a ser una fase real, el 2FA pasa a ser obligatorio o un taller quiere entrar con la cuenta de su empresa (SSO). **Híbrido** (SuperTokens para el personal, sesión propia para el portal): dos sistemas de sesión que mantener. **Autenticación propia**: habría que escribir y probar uno mismo la rotación, la revocación y el CSRF. |
| A5 | Separación de actores en la API | **Tres prefijos**: `/api/v1/workshop/*`, `/api/v1/portal/*` y `/api/v1/admin/*`. Cada uno tiene una dependencia **a nivel de router** que exige su actor y rechaza cualquier otro | **Comprobar el actor en cada endpoint**: basta con olvidarlo una vez. Con el router, un endpoint nuevo queda protegido por construcción. |
| A5b | Rutas sin sesión | **Dos prefijos más, sin sesión**, para aceptar una invitación, porque quien la usa aún no tiene cuenta: `/api/v1/invitations` (empleados; el taller viaja en la URL y se fija para RLS antes de buscar el token) y `/api/v1/superadmin-invitations` (superadministradores; sin taller, por la vía de plataforma, §4). Añadidos en F1 | **Meterla en `/workshop`** exigiría una sesión que esa persona todavía no tiene. **Un prefijo genérico `/public`** invitaría a añadir ahí cualquier cosa sin pensar en quién la usa. |
| A6 | Taller activo | **Llega en cada petición** del personal (cabecera `X-Workshop-Id`) y se valida contra los empleados activos del usuario (RNF-09) | **Guardarlo en la sesión**: cambiar de taller obligaría a renovar la sesión, y dos pestañas no podrían trabajar en talleres distintos. |
| A7 | Aislamiento entre talleres | **Dos capas en la base de datos además del filtro de la aplicación**: claves foráneas compuestas `(workshop_id, id)`, que impiden enlazar datos de dos talleres, y **Row-Level Security**, que impide leer o escribir filas de otro taller aunque una consulta olvide filtrar | **Solo FK compuestas** (como Applications Tracker): un filtro olvidado devolvería datos de otro taller, y solo lo cazarían las pruebas. Con varios talleres, ese error es el más probable y el más grave. |
| A8 | Trabajo en segundo plano | **Valkey + SAQ** con un servicio `worker`, también para los trabajos programados (recordatorios, vencimientos, caducidad de presupuestos, borrado de firmas). Heredado | **Celery**: más pesado para el mismo uso. **cron del sistema**: fuera de Docker, sin reintentos ni registro. |
| A9 | Documentos | **PDF generados con WeasyPrint + Jinja2**. Heredado. **Sin almacén de ficheros**: no hay ficheros subidos (RF-50), y la firma en pantalla se guarda como dato en la base de datos | **Un almacén de ficheros "por si acaso"**: un servicio, un volumen y unas copias de seguridad para nada. Añadirlo después no obliga a rehacer nada (especificación §12). |
| A10 | Correo | **SMTP de la plataforma** para todo (RF-68); **Mailpit** en desarrollo. Heredado | **SMTP por taller**: descartado en la especificación (R12). |
| A11 | Borradores sin conexión | **IndexedDB en el navegador** para lo que se está escribiendo (RNF-22), con aviso de conflicto al enviar (RNF-15). *Al construirlo en F2* (`workshop/lib/drafts.ts` y `useDraft.ts`): sin dependencias, una clave por usuario, taller, orden y tipo; el formulario guarda a cada cambio, lo que falló por la conexión queda pendiente y se reenvía al volver con la orden abierta (o al abrirla), y la cabecera dice si no hay conexión y qué falta por enviar. Las mutaciones de estos formularios usan `networkMode: "always"`: TanStack Query, sin conexión, las dejaría en pausa en vez de fallar | **Funcionar sin conexión de verdad**: sincronización y resolución de conflictos, casi un proyecto aparte. |
| A12 | Documentación | **MkDocs** para `docs/` (desarrollo) y **Docusaurus** para el manual de producción en es y en, que se escribe en F9. Heredado | **Solo MkDocs**: mezclaría la documentación de quien programa con la de quien usa el taller. |
| A13 | Entrega | **CI en GitHub Actions desde F1** y **despliegue en Coolify desde F2**. Desde ahí, cada fase termina en producción | **Desplegar al final**: los problemas de despliegue aparecerían todos juntos y tarde. |

> Lo que **desaparece** respecto a Applications Tracker: Ollama y toda la IA, el almacén de ficheros, la suscripción ICS y `dnd-kit`. Lo que **es nuevo**: la receta `passwordless` de SuperTokens, RLS, la segunda aplicación de frontend, la captura de firma (`signature_pad`) y los borradores en IndexedDB.

## 2. Autenticación de tres actores

### Tres significados de "rol"

En este proyecto "rol" quiere decir tres cosas distintas, en tres capas que no se mezclan:

| Capa | Qué responde | Valores | Dónde vive | Quién lo comprueba |
|---|---|---|---|---|
| **Rol de base de datos** | ¿Con qué credenciales se conecta **el proceso** a Postgres? | `axtton_owner`, `axtton_app`, `axtton_platform` | Postgres (§4) | Postgres: permisos y RLS |
| **Actor** | ¿Qué **tipo de persona** ha iniciado sesión? | `staff`, `client`, `superadmin` | La sesión de SuperTokens (abajo) | La dependencia del router de cada prefijo (A5) |
| **Rol en el taller** | ¿Qué puede hacer **este empleado en este taller**? | `admin`, `mechanic` | `employees.role`, uno por taller | La función de permisos de `domain/` (RNF-03) |

- **Los roles de base de datos no representan personas.** Todas las peticiones del personal y de los clientes usan `axtton_app`, sea quien sea quien las hace. Solo el código de `app/platform/` usa `axtton_platform`.
- **RLS solo sabe de talleres, no de personas.** Separa el taller A del B, pero no sabe si quien pregunta es un mecánico o un cliente. Eso lo deciden las otras dos capas: que un mecánico no envíe presupuestos lo decide su rol en el taller, y que un cliente vea solo sus órdenes, los repositorios del portal.
- **Alternativa descartada: un rol de Postgres por usuario o por taller.** Es tentador, porque Postgres comprobaría los permisos de cada persona. Pero obligaría a abrir una conexión con credenciales distintas en cada petición, lo que rompe el pool de conexiones. Además, crear un usuario sería crear un rol de base de datos, algo que solo puede hacer un superusuario (decisión 0001).

### Quién entra y cómo

| Actor | Receta de SuperTokens | Cómo entra | Qué lleva su sesión | A qué rutas llega |
|---|---|---|---|---|
| Personal (administrador, mecánico) | `emailpassword` | Email y contraseña | `actor: "staff"` | `/api/v1/workshop/*`, con el taller activo en cada petición (A6) |
| Superadministrador | `emailpassword` | Email y contraseña | `actor: "superadmin"` | `/api/v1/admin/*` |
| Cliente | `passwordless` (enlace mágico) | Enlace por email | `actor: "client"`, `workshop_id`, `client_id` | `/api/v1/portal/*`, solo de ese taller y ese cliente |

- **El actor lo escribe el backend una sola vez: al crear la sesión**, en un único sitio, `app/core/sessions.py`, y nunca cambia durante la vida de la sesión. Ningún otro código modifica el contenido de una sesión ya creada (la función de SuperTokens que lo permite no se usa fuera de ahí, T11). Ese sitio sobrescribe `create_new_session`, la función interna de SuperTokens que **todas** las recetas llaman al crear una sesión: así no hay ninguna vía para crear una sesión sin pasar por él. El diseño original hablaba de una función propia (`create_session_for`); al construirlo en F1 resultó más seguro engancharse a la de SuperTokens. El actor se lee siempre de la sesión verificada, nunca de una cabecera ni del cuerpo de la petición. El token va firmado: un actor editado a mano invalida la firma (T9).
- **Superadministradores y personal son cuentas distintas.** Un superadministrador no es un empleado con un permiso de más: si la misma persona trabaja también en un taller, usa otra cuenta. Así RNF-08 se cumple sin excepciones. Se comprueba en las dos direcciones: una cuenta de superadministrador no acepta una invitación de empleado (`superadmin_cannot_be_employee`), y una de personal no acepta una de superadministrador (`staff_cannot_be_superadmin`).
- **El primer superadministrador sale de un comando; los demás, de una invitación** de uno que ya lo es (RF-110), en `/admin/superadmins`.
- **Un mismo email en las dos recetas son dos usuarios distintos** de SuperTokens. No se usa la vinculación de cuentas (*account linking*), que además es de pago: activarla uniría la cuenta de cliente de alguien con su cuenta de personal, y exigiría una decisión nueva en la bitácora. Que Ana sea mecánica en un taller y clienta de otro no mezcla nada.
- **Una sesión de cliente vale para un solo taller.** El enlace mágico lleva el taller (RF-45), y al consumirlo el backend comprueba que ese email es un cliente activo de ese taller antes de crear la sesión con su `workshop_id` y su `client_id`. Si el email es cliente de varios talleres, recibe un enlace por taller y cada uno crea una sesión distinta.
- **Cookies httpOnly en el navegador y token Bearer fuera de él**, como en Applications Tracker (su decisión 0003). Es la costura para las apps móviles.
- **Las rutas de SuperTokens cuelgan de `/api/auth`**, como el resto de la API, para que el proxy solo tenga que reenviar `/api`.
- **No hay registro público** (RF-01): la operación de registro de SuperTokens está anulada y responde `signup_disabled` en todas sus rutas. Las cuentas las crea el backend con la función de la receta: el comando del superadministrador y la aceptación de invitaciones.
- **Una cuenta de SuperTokens sin fila en `users` no inicia sesión**, y responde como una contraseña incorrecta. Puede quedar una si algo falla a medias al aceptar una invitación.

### Cómo se cierra cada puerta

```mermaid
flowchart LR
    R[Petición] --> S{¿Sesión válida?}
    S -- no --> E401[401]
    S -- sí --> P{Prefijo}
    P -- /workshop --> T{actor = staff<br/>y empleado activo<br/>en X-Workshop-Id}
    P -- /portal --> C{actor = client<br/>y cliente activo<br/>en su taller}
    P -- /admin --> A{actor = superadmin}
    T -- no --> E404[404 / 403]
    C -- no --> E404
    A -- no --> E404
    T -- sí --> OK[Endpoint, con taller fijado para RLS]
    C -- sí --> OK
    A -- sí --> OK2[Endpoint de plataforma, sin datos de talleres]
```

Cada prefijo es un router con su dependencia. Esa dependencia, además de comprobar el actor, **fija el taller de la transacción** para RLS (A7). El endpoint no tiene que acordarse de nada.

### Pruebas adversas

| # | Qué se intenta | Resultado esperado |
|---|---|---|
| T1 | Cada ruta de `/workshop`, `/portal` y `/admin` sin sesión | 401. Las rutas se leen del OpenAPI, no de una lista a mano, y una prueba de control falla si encuentra demasiado pocas |
| T2 | Cada ruta de cada prefijo con una sesión de **los otros dos** actores | Rechazada siempre |
| T3 | Un empleado envía `X-Workshop-Id` de un taller en el que no trabaja | 404, como si no existiera |
| T4 | Un cliente del taller A usa su sesión para leer una orden del taller B, o de otro cliente de A | 404 |
| T5 | Un enlace mágico del taller A con el taller cambiado a B en la URL | No crea sesión |
| T6 | Usar dos veces el mismo enlace mágico | La segunda falla |
| T7 | Anonimizar a un cliente en el taller A cuando su email también es cliente en B | Se cierran sus sesiones de A; la de B sigue viva |
| T8 | Desactivar a un empleado con la sesión abierta | Su siguiente petición se rechaza (RF-06) |
| T9 | Una petición con el contenido del token modificado a mano (por ejemplo, `actor` cambiado de `client` a `staff`) | 401: la firma no coincide |
| T10 | Consumir un enlace mágico, también con un email que es a la vez de personal en otro taller | La sesión creada es siempre `actor: client`, con el taller del enlace |
| T11 | Buscar en el código llamadas que modifiquen el contenido de una sesión ya creada | Ninguna fuera de `app/core/sessions.py`; la prueba revisa el código, como R8 revisa los imports |

F1 cubre T1, T2, T3, T8, T9 y T11. T4, T5, T6, T7 y T10 hablan del cliente y llegan con el portal (F4).

### Límite de peticiones (RNF-06)

Hecho en F1, heredado de Applications Tracker: la librería `limits` con **ventana deslizante** sobre Valkey (`app/infra/rate_limit.py`), reglas puras en `app/domain/rate_limits.py`. Al superar una regla se responde 429 `rate_limited` con `Retry-After`; nunca se bloquea la cuenta, porque bastaría saber un email para dejar a alguien sin acceso.

| Qué | Reglas |
|---|---|
| Inicio de sesión | 10 por hora por email; 30 por minuto por IP (holgado: el personal de un taller comparte IP) |
| Recuperación de contraseña | 3 por hora por email; 10 por hora por IP |
| Ver una invitación | 60 por hora por IP |
| Aceptar una invitación | 5 cada 15 minutos por enlace; 20 por hora por IP. Aceptar con una cuenta existente exige su contraseña (RF-07): sin límite, un enlace serviría para probarlas |
| Cambiar la contraseña | 5 cada 15 minutos por usuario, contados **antes** de comprobar la actual |
| Pedir un enlace mágico | Llega con el portal, en F4 |

- Las rutas de SuperTokens no admiten dependencias de FastAPI: las limita un middleware colocado **por fuera** del suyo, que reconoce todas sus formas equivalentes (`/api/auth/signin/`, `/api/auth/public/signin`, `;x`) para que cambiar la URL no salte el límite.
- La IP es la de la conexión; `X-Forwarded-For` solo cuenta si viene de un proxy de `TRUSTED_PROXIES`, leído por la derecha.
- Si Valkey no responde, **se deja pasar** durante 30 s: mejor un rato sin límite que nadie pueda entrar.

### Trampas ya identificadas

- **Revocar las sesiones de un cliente no es revocar las de su usuario de SuperTokens.** El usuario passwordless es uno por email, compartido entre talleres. Anonimizar a un cliente o cambiarle el email (RF-47) debe cerrar solo las sesiones cuyo `workshop_id` y `client_id` coinciden; `revokeAllSessionsForUser` cerraría también las de otros talleres. Por lo mismo, anonimizar nunca borra el usuario de SuperTokens si ese email sigue siendo cliente de otro taller (T7).
- **RLS y el pool de conexiones.** El taller de la petición se fija con `set_config('app.workshop_ids', …, true)`: el `true` lo limita a la transacción. Sin él, el valor se queda en la conexión y la siguiente petición que la reutilice vería el taller anterior.
- **RLS no se aplica al dueño de las tablas.** La aplicación debe conectarse con un rol que no sea el propietario de las tablas, y las tablas llevan `FORCE ROW LEVEL SECURITY`. Si no, todas las políticas pasan sin que nada falle. Las migraciones usan el rol propietario y la aplicación el otro.
- **Las vías que cruzan talleres son explícitas.** El `worker`, el resumen entre talleres (RF-09) y el superadministrador necesitan leer más de un taller. Lo hacen por una vía separada y nombrada, nunca desactivando RLS en la conexión normal.

## 3. Modelo de datos

### Convenciones

Heredadas de Applications Tracker, salvo donde se dice:

- **Nombres de tablas y columnas en inglés**, en `snake_case`. El taller es `workshop`; la orden de trabajo, `work_order`; el presupuesto, `quote`.
- **Clave primaria** `id uuid DEFAULT gen_random_uuid()`.
- **`created_at timestamptz NOT NULL DEFAULT clock_timestamp()`**. No se usa `now()`, que da la misma hora a todas las filas de una transacción (decisión 0001 de Applications Tracker). Las tablas que se editan llevan además `updated_at`; las append-only, no.
- **Los historiales se ordenan por `seq bigint GENERATED ALWAYS AS IDENTITY`**, nunca por fecha, porque el reloj puede retroceder (decisión 0004 de Applications Tracker).
- **Enumerados como `varchar` con `CHECK`**, no como tipos `ENUM` de Postgres: añadir un valor es cambiar un `CHECK`, no una migración delicada.
- **Importes en `bigint` de céntimos** (RNF-10). Tipos de IVA en puntos básicos (`smallint`: 2100 = 21 %). Cantidades en `numeric(10,3)`, porque se venden litros de aceite.
- **Fechas en `timestamptz`** (UTC en la base de datos); se muestran en la zona horaria del taller (`workshops.timezone`).
- **Bloqueo optimista**: las tablas editables por varias personas llevan `version integer NOT NULL DEFAULT 1`, y un `UPDATE … WHERE version = :esperada` que no afecta a ninguna fila es un conflicto (RNF-15).

**La regla del multi-taller, nueva respecto a Applications Tracker:** **toda tabla de un taller lleva su propia columna `workshop_id NOT NULL`, también las tablas hijas**, aunque se pudiera deducir del padre. Cada tabla tiene además `UNIQUE (id, workshop_id)`, y sus claves foráneas son compuestas: `(parent_id, workshop_id) → parent(id, workshop_id)`.

- **Qué consigue:** que la base de datos impida enlazar una línea de presupuesto del taller A con un presupuesto del taller B, y que la política de RLS (§4) sea una comparación de una columna, sin joins.
- **Tres excepciones a `UNIQUE (id, workshop_id)`:** `audit_log` (su `workshop_id` puede ser nulo, las acciones de plataforma, y ninguna tabla la referencia), `work_order_counters` (*al construirlo en F2*: su clave primaria es `(workshop_id, year)`, no tiene `id` y nadie la referencia) y `workshop_logos` (*F3*: su clave es el taller). Ninguna tiene una FK compuesta que lo pida. Las tres llevan la política de RLS, y la fila nula de `audit_log` no la ve ningún taller.
- **Qué cuesta:** una columna repetida por tabla.

### Mapa

```mermaid
erDiagram
    workshops ||--o{ employees : ""
    users |o--o{ employees : "acceso opcional"
    workshops ||--o{ clients : ""
    workshops ||--o{ vehicles : ""
    vehicles ||--|{ vehicle_ownerships : ""
    clients ||--o{ vehicle_ownerships : ""
    vehicles ||--o{ work_orders : ""
    clients ||--o{ work_orders : "titular al abrir"
    work_orders ||--|{ work_order_status_changes : ""
    work_orders ||--o{ diagnosis_versions : ""
    work_orders ||--o{ internal_notes : ""
    work_orders ||--o{ work_entries : ""
    work_orders ||--o| reception_sheets : ""
    work_orders ||--o{ quotes : "versiones"
    quotes ||--|{ quote_lines : ""
    quotes ||--o| quote_decisions : ""
    workshops ||--o{ parts : ""
    parts ||--o{ stock_movements : ""
    work_orders ||--o{ used_parts : ""
    used_parts ||--o{ stock_movements : ""
    workshops ||--o{ appointments : ""
    appointments |o--o| work_orders : "se convierte en"
    workshops ||--o{ notifications : ""
```

| Tabla | Para qué | Notas |
|---|---|---|
| `users` | Cuentas del personal y del superadministrador, enlazadas con SuperTokens | **Fuera de los talleres** (sin `workshop_id`). `kind`: `staff` o `superadmin`. No guarda email ni contraseña: eso vive en SuperTokens |
| `workshops` | El taller: datos legales, registro industrial, zona horaria, ajustes (IVA por defecto, validez del presupuesto ≥ 12 días hábiles, plazo de conservación de firmas, si el mecánico ve importes, aforo por franja), estado y límites ajustados. *Límites (F2, migración `0010limits`):* una columna `max_*` por recurso con su CHECK y el valor del plan básico por defecto (`domain/limits.py`); solo los escribe la plataforma. *Datos del taller (F3, migración `0012settings`):* `axtton_app` puede actualizar solo los datos legales y los ajustes que edita su administrador (RF-02): nombre, razón social, NIF, dirección, teléfono, email de respuesta, registro industrial, IVA por defecto, validez del presupuesto y si el mecánico ve importes. El estado, la zona horaria, los límites y el plazo de las firmas siguen siendo de la plataforma. Cada alta llama antes que a nada a `services/limits.py::ensure_room`, que pone en fila el recuento con un bloqueo consultivo por taller y recurso: sin él, dos altas a la vez cabrían en el último hueco (`test_concurrency.py`) | Raíz del aislamiento |
| `employees` | Ficha del personal con su rol | `user_id` opcional; `UNIQUE (workshop_id, user_id)` |
| `invitations` | Invitaciones de acceso (RF-04, RF-112) | Token guardado como hash, caducidad, un solo uso |
| `superadmin_invitations` | Invitaciones para ser superadministrador (RF-110) | Igual que `invitations`, pero de plataforma: sin taller ni RLS, y `axtton_app` no tiene ningún permiso sobre ella. Una invitación nueva anula las pendientes del mismo email; aceptar con el email de una cuenta de personal se rechaza (§2) |
| `labor_rates` | Tarifas de mano de obra con nombre | **Existe (F3, migración `0012settings`).** Precio por hora en céntimos, sin IVA. Como mucho una por defecto (índice único parcial; la primera lo es sola, y para quitar la marca se pone en otra), nombre único entre las vigentes y 20 vigentes como mucho. No se borran: se archivan. Los cambios en conjunto (cuál es la de por defecto, cuántas hay) se ponen en fila con un bloqueo consultivo por taller (`lock_labor_rates`). Una línea de presupuesto copia su nombre y su precio, nunca la referencia (RF-38) |
| `workshop_logos` | El logotipo del taller ([decisión 0005](../decisiones/0005-logotipo-del-taller-como-unica-imagen-subida.md)) | **Existe (F3).** El PNG que dibuja el servidor, nunca lo subido. Su clave es el taller, sin `id` (otra excepción a `UNIQUE (id, workshop_id)`, como `work_order_counters`); aparte de `workshops` para que no viaje en cada petición |
| `clients` | Clientes del taller | **Existe (F2).** `kind` (particular o empresa), teléfono obligatorio, email y NIF opcionales y normalizados al guardar (minúsculas; mayúsculas sin separadores). **Email único por taller** (índice parcial `(workshop_id, email) WHERE email IS NOT NULL`): es la llave del portal y dos clientes con el mismo email harían ambiguo el enlace mágico (§7.2). Se archiva con `archived_at`; `axtton_app` **no tiene `DELETE`** (migración `0004clients`). Para la búsqueda del mostrador (RF-14), dos columnas generadas: `name_search` (`search_text(name)`: minúsculas y sin tildes) y `phone_digits` (solo los dígitos), migración `0008search`. Llegará `maintenance_reminders_opt_out_at` (RF-66, F8). *Anonimizar (F2, migración `0009payment`):* `anonymized_at`, y un CHECK que exige entonces nombre y teléfono vacíos, lo opcional nulo y el cliente archivado; el trigger `clients_anonymized_frozen` impide volver a tocar la fila con ningún rol |
| `vehicles` | Vehículos | **Existe (F2).** `plate_normalized` único por taller (mayúsculas, sin espacios, guiones ni puntos) y `plate` tal como se escribió; VIN opcional, normalizado y **único por taller** si existe (un VIN repetido suele ser el mismo coche dado de alta dos veces); marca y modelo en texto libre con sugerencias (`GET /workshop/vehicles/suggestions`); vencimientos (ITV, revisión por fecha y km). El titular no es una columna. `axtton_app` no tiene `DELETE` |
| `vehicle_ownerships` | Periodos de titularidad | **Existe (F2). Crítica**, ver más abajo |
| `work_orders` | Órdenes de trabajo | **Existe (F2). Crítica** |
| `work_order_counters` | El último número de orden por taller y año | **Existe (F2).** Ver la trampa de la numeración; un trigger impide que baje |
| `work_order_status_changes` | Historial de estados, append-only | **Existe (F2). Crítica** |
| `diagnosis_versions` | Versiones del texto de diagnóstico para el cliente | **Existe (F2).** Append-only; la vigente es la de `version_no` más alto. `UNIQUE (work_order_id, version_no)` es además su bloqueo optimista: quien guarda manda la versión desde la que editó (`base_version_no`), y dos que guardan desde la misma intentan escribir la misma siguiente, así que la segunda choca (409) |
| `internal_notes` | Hilo de notas internas | **Existe (F2).** Append-only (nadie edita lo de otro, RF-22), ordenado por `seq`; se admiten con la orden cerrada (RF-26) |
| `work_entries` | Trabajos realizados | **Existe (F2).** `employee_id` es quien lo hizo; `recorded_by_employee_id`, quien lo anotó. No se edita ni se borra: se **anula** (`voided_at`, `voided_by_employee_id`, las únicas columnas que `axtton_app` puede escribir; un trigger impide lo demás). Lo anula quien lo anotó o el administrador. Los mecánicos que han trabajado (RF-25) salen de los trabajos sin anular; uno sin anular impide cancelar la orden |
| `reception_sheets` | Hoja de recepción y su firma | Una por orden; congelada al firmarse (RF-52, RF-56) |
| `quotes` | Cada **versión** de presupuesto | **Crítica** |
| `quote_lines` | Líneas de una versión | **Crítica** |
| `quote_decisions` | Aprobación o rechazo | **Crítica**, append-only |
| `parts` | Catálogo de piezas | `UNIQUE (workshop_id, lower(reference))` |
| `used_parts` | Piezas montadas en una orden | Quitar una no la borra: se marca y genera el movimiento contrario |
| `stock_movements` | Libro de movimientos de stock | **Crítica**, append-only |
| `appointments` + `appointment_changes` | Citas y su historial de cambios | `source` (costura para la reserva desde el portal) |
| `notifications` | Bandeja de salida de avisos | `UNIQUE (workshop_id, dedupe_key)`: la garantía de "nunca dos veces" (RF-62) |
| `audit_log` | Registro de acciones sensibles (RNF-16) | Append-only; `workshop_id` nulo en las acciones de plataforma. Se escribe en la misma transacción que el cambio, así que un cambio deshecho no deja rastro. Se consulta por `seq` descendente con `?before=`: el administrador, en `GET /workshop/audit` (bajo RLS, con los nombres de las fichas de su taller); el superadministrador, en `GET /admin/audit`, solo las filas de `workshop_id` nulo, con el email de quien actuó |

### Las tablas que hay que acertar a la primera

Son las que, si se diseñan mal, obligan a migrar datos con valor de prueba. Del resto se puede cambiar casi todo con una migración corriente.

#### `work_orders` y `work_order_status_changes`

El estado de una orden es una copia del último cambio de su historial (especificación §6), como en Applications Tracker.

| Columna de `work_orders` | Tipo | Notas |
|---|---|---|
| `workshop_id` | `uuid NOT NULL` | |
| `year`, `number` | `smallint`, `integer NOT NULL` | `UNIQUE (workshop_id, year, number)`; se muestra como `OT-2026-0042` (RF-21) |
| `type` | `varchar(20) NOT NULL` | `CHECK IN ('breakdown','maintenance','itv','warranty','bodywork','other')` |
| `vehicle_id`, `client_id` | `uuid NOT NULL` | FK compuestas. `client_id` es el titular **al abrir** (RF-20) y no cambia nunca |
| `responsible_employee_id` | `uuid` | Nulo hasta que se asigna (RF-25) |
| `status` | `varchar(30) NOT NULL` | Copia del último cambio |
| `unrepaired` | `boolean NOT NULL DEFAULT false` | "Lista · sin reparar" (§6 de la especificación) |
| `no_quote_reason` | `varchar(20)` | `CHECK IN ('waiver','warranty','fixed_price')`; `waiver` exige una hoja de recepción firmada con la renuncia (RF-27) |
| `warranty_of_id` | `uuid` | La orden original de una orden de garantía |
| `odometer_km`, `reason`, `expected_delivery_at`, `dropped_off_by_name`, `dropped_off_by_phone`, `reception_notes` | | Datos de recepción (RF-20). *Al construirlo:* quien trae el coche, en dos columnas (nombre y teléfono), y las observaciones de recepción (daños visibles, objetos) en la orden |
| `delivered_at` | `timestamptz` | Lo fija el paso a `entregada`; de aquí sale la garantía (RF-53) y el plazo de la firma (RF-56) |
| `payment_status`, `payment_method`, `paid_amount_cents`, `paid_on` | | El cobro (RF-28). No es un estado. *Al construirlo (F2, `0009payment`):* `payment_status` es `pending`, `paid` o `no_charge` (sin cargo: una garantía o un diagnóstico gratuito no deben quedar para siempre entre las pendientes); `paid_on` es una fecha (el día del cobro, que puede ser anterior a anotarlo), no un instante. Dos CHECK: solo una cerrada deja de estar pendiente, y forma, importe y fecha van si y solo si está cobrada. Índice parcial `ix_work_orders_unpaid` para RF-29 |
| `last_activity_at` | `timestamptz NOT NULL` | Para "las que llevan más tiempo paradas" (RF-24) |
| `version` | `integer NOT NULL` | Bloqueo optimista |

| Columna de `work_order_status_changes` | Notas |
|---|---|
| `workshop_id`, `work_order_id` | FK compuesta |
| `seq` | Identidad. **El orden del historial** |
| `from_status`, `to_status` | |
| `cause` | `CHECK IN ('opened','manual','quote_sent','quote_decided','quote_cancelled','undo')`. Solo `manual` se puede deshacer (§6 de la especificación). *Añadido en F2:* `opened`, el primer cambio de toda orden (de nada a `received`), para que el invariante se cumpla también recién abierta; un `CHECK` exige que solo él no venga de ningún estado |
| `undoes_seq` | El cambio que compensa, si `cause = 'undo'` |
| `notified` | Si este cambio envió un aviso al cliente; entonces no se puede deshacer |
| `employee_id` / `by_client` | Quién lo provocó |
| `note` | Obligatoria para cancelar y para "sin reparar" |

**Invariante:** `work_orders.status` es igual al `to_status` del cambio con el `seq` más alto de esa orden. Todo cambio de estado bloquea la orden con `SELECT … FOR UPDATE` antes de leer el último cambio.

*Lo añadido al construirlo (F2, migración `0006orders`):*

- **El invariante lo vigila también la base de datos.** `work_order_status_matches_history` es un `CONSTRAINT TRIGGER` diferido sobre las dos tablas. Al confirmar, comprueba cada orden tocada: un estado sin su cambio, un cambio sin mover la orden o una orden sin su primer cambio hacen fallar la transacción entera. Es una red de seguridad: lo normal es que el service escriba los dos.
- **Abrir una orden** (`POST /workshop/orders`, RF-20) sigue este orden: bloquea el vehículo con `FOR SHARE`, lee su titular, pide el número y escribe la orden con su primer cambio (`opened`). El bloqueo compartido pone en fila la apertura con un cambio de titular, que pide `FOR UPDATE`. Tiene que ir **antes** de leer el titular: la comprobación de la FK hacia `vehicles` también espera al cambio, pero llega tarde, con el titular ya leído (`test_concurrency.py`).
- **El año de la numeración es el del taller**, calculado en la base de datos con `AT TIME ZONE workshops.timezone`, no el de UTC.
- **Permisos:** `axtton_app` no tiene `DELETE` sobre `work_orders` (una orden abierta por error se cancela) ni sobre `work_order_counters`, y no tiene `UPDATE` ni `DELETE` sobre `work_order_status_changes` (RNF-12).
- **Las transiciones manuales** (F2, paso 4) son una tabla en `domain/work_orders.py` (`TRANSITIONS`): cada una dice qué acción de la matriz de permisos la autoriza (`MOVE_REPAIR_STATUS`, que tiene también el mecánico, o `MANAGE_ORDERS`), si exige nota (cancelar, "sin reparar") y si exige "sin presupuesto" (RF-27). Las del presupuesto no están: no se hacen a mano. `POST /workshop/orders/{id}/status` las aplica con la orden bloqueada (`FOR UPDATE`) y su versión comprobada. La ficha devuelve `allowed_transitions` para el rol de quien la mira, así que la interfaz no repite las reglas.
- **Deshacer** (`POST /workshop/orders/{id}/undo`) escribe un cambio con causa `undo` y `undoes_seq`, vuelve al estado anterior (y quita la marca "sin reparar" si era eso) y se audita. Solo se deshace un último cambio `manual`, no notificado y que no cerró la orden.
- **El bloqueo y la versión, comprobados rompiendo el bloqueo:** sin el `FOR UPDATE`, dos cambios simultáneos siguen sin pisarse, porque SQLAlchemy vigila la `version` al escribir la orden y el segundo choca (`StaleDataError` → 409). Pero entonces es el ORM, al final, quien detecta el conflicto, no el service con sus reglas. El bloqueo es lo que hace que el service lea el último cambio de verdad; la versión es la red. En F3, cuando el presupuesto cambie el estado sin que nadie mande una versión, el bloqueo será lo único que quede.
- **Qué bloqueo pide cada escritura sobre una orden** (F2, paso 5):
  - un cambio de estado pide `FOR UPDATE`;
  - guardar el diagnóstico o anular un trabajo pide `FOR SHARE`: solo necesita que la orden no cambie de estado mientras tanto;
  - **registrar un trabajo pide `FOR NO KEY UPDATE`**, porque además actualiza la orden (`last_activity_at`). Con `FOR SHARE`, dos trabajos a la vez podrían coger los dos su bloqueo compartido y esperarse luego el uno al otro para actualizar: un interbloqueo que Postgres resuelve abortando a uno. La prueba lo provoca a propósito y, con `FOR SHARE`, falla con `deadlock detected`.

  Gracias a eso, cancelar (que exige no tener trabajos) y anotar un trabajo nunca pasan los dos: el segundo espera y ve lo que hizo el primero. `last_activity_at` se escribe con un `UPDATE` directo, sin subir la `version`, para que un trabajo no provoque un 409 a quien edita la recepción.
- **El directorio del personal** (`GET /workshop/staff`): id y nombre de las fichas activas, para todo el personal. Hace falta para anotar el trabajo de un compañero (RF-23) sin abrirle al mecánico `/employees`, que incluye costes y accesos.
- **El cobro** (`PUT /workshop/orders/{id}/payment`, F2 paso 8): solo con la orden cerrada (RF-26), con la orden bloqueada y su versión comprobada, y auditado (`payment_recorded`, solo lo que cambió). Se puede corregir: es una marca operativa, no una factura. `GET /workshop/orders/unpaid` da las entregadas pendientes, la más antigua primero, con los días pendientes calculados en la zona del taller; el importe a cobrar llegará con los presupuestos (F3).

#### `quotes`, `quote_lines` y `quote_decisions`

Una fila de `quotes` es **una versión**, no "el presupuesto". Así, versionar es insertar, y congelar es dejar de permitir cambios.

| Columna de `quotes` | Notas |
|---|---|
| `work_order_id`, `version_no` | `UNIQUE (work_order_id, version_no)` |
| `status` | `CHECK IN ('draft','sent','approved','rejected','expired','superseded','cancelled')` |
| `sent_at`, `valid_until` | `valid_until` se calcula al enviar: al menos 12 días hábiles (RF-33) |
| `origin_status` | El estado de la orden al enviarla: adonde vuelve tras decidir o anular (§6 de la especificación) |
| `diagnosis_version_id` | La versión del diagnóstico que acompañaba al envío |
| `global_discount_kind`, `global_discount_value` | Porcentaje o importe (RF-39) |
| `subtotal_cents`, `vat_breakdown jsonb`, `total_cents` | **Se guardan al enviar** y no se recalculan nunca (RNF-11, RNF-14) |
| `cancel_reason` | |

Restricción: **índice único parcial** `(work_order_id) WHERE status = 'sent'`. La base de datos impide que haya dos versiones enviadas a la vez.

| Columna de `quote_lines` | Notas |
|---|---|
| `position` | Orden de la línea |
| `kind` | `CHECK IN ('labor','part','other')` |
| `description`, `reference` | **Copiados** del catálogo o de la tarifa, nunca referenciados (RF-38) |
| `part_id` | Solo informativo, para RF-97; nulo si la pieza se borró del catálogo |
| `part_condition` | `CHECK IN ('new','used','reconditioned','non_specific')` (RF-38) |
| `quantity`, `unit_price_cents`, `discount_bp`, `vat_bp` | |
| `global_discount_share_cents` | Lo que le toca del descuento global, repartido al enviar (RF-39) |
| `line_total_cents` | Guardado al enviar |
| `optional` | Costura para la aprobación por líneas, sin usar |

`quote_decisions`: `quote_id UNIQUE`, `outcome` (`approved` o `rejected`), `channel` (`portal`, `phone` o `in_person`), `recorded_by_employee_id` (nulo si decidió el cliente en el portal), `ip`, `user_agent`, `note`, `decided_at`.

**Cómo se garantiza la inmutabilidad (RNF-11)**, en dos niveles:

1. **Permisos.** El rol de la aplicación no tiene `UPDATE` ni `DELETE` sobre `quote_decisions` (§4).
2. **Trigger.** Uno en `quote_lines` rechaza cualquier `INSERT`, `UPDATE` o `DELETE` si su versión no está en `draft`. Otro en `quotes` solo permite, una vez enviada, los cambios de `status` del ciclo de vida.

Un fallo de la aplicación no puede alterar un presupuesto enviado.

#### `vehicle_ownerships`

| Columna | Notas |
|---|---|
| `vehicle_id`, `client_id` | FK compuestas |
| `started_at`, `ended_at` | `ended_at` nulo = titular actual |

Hay dos restricciones, para que nunca haya dos titulares a la vez:

- **Un solo titular actual:** índice único parcial `(vehicle_id) WHERE ended_at IS NULL`.
- **Periodos que no se solapan:** `EXCLUDE USING gist (vehicle_id WITH =, tstzrange(started_at, ended_at) WITH &&)`. Necesita la extensión `btree_gist`, que es *trusted*: la crea la propia migración con el dueño de la base, sin superusuario. El rango es `[inicio, fin)`, así que un periodo que acaba en el instante exacto en que empieza el siguiente no lo pisa.

*Lo añadido al construirlo (F2, migración `0005vehicles`):*

- **Un periodo cerrado no cambia nunca.** El trigger `vehicle_ownerships_closed_frozen` rechaza, con cualquier rol, tocar un periodo ya cerrado o cambiar el vehículo, el cliente o el inicio de uno abierto: cambiar de titular es cerrar y abrir, nunca reescribir. `axtton_app` solo tiene `UPDATE (ended_at)` y no tiene `DELETE`.
- **Un vehículo nace con su titular y nunca se queda sin él.** El alta crea el primer periodo en la misma transacción. El cambio de titular (`POST /workshop/vehicles/{id}/owner`, RF-12) bloquea el vehículo con `SELECT … FOR UPDATE`, comprueba su `version`, cierra el periodo abierto y abre el nuevo con **la misma hora de la base de datos** (`clock_timestamp()`). Después toca el vehículo para que suba su `version`: quien tuviera la ficha abierta recibe un 409. Se audita (`vehicle_owner_changed`) con los ids de los clientes, no con sus nombres. Los nombres se ponen al leer el registro, así que anonimizar a un cliente (RF-15) no deja su nombre en una tabla append-only.
- **Sin el bloqueo**, dos cambios simultáneos leerían el mismo periodo abierto, y el segundo chocaría con el trigger (un 500). Con él, el segundo espera y recibe un 409 (`test_concurrency.py`).

El acceso del cliente en el portal **no** sale de esta tabla, sino de `work_orders.client_id` (RF-44). Esta tabla responde "¿quién es el titular hoy?" y "¿desde cuándo?".

#### `stock_movements`

| Columna | Notas |
|---|---|
| `part_id` | FK compuesta |
| `kind` | `CHECK IN ('in','out','adjustment','reversal')` |
| `quantity` | Con signo: positivo entra, negativo sale |
| `unit_cost_cents` | En las entradas |
| `work_order_id`, `used_part_id` | Origen de las salidas |
| `reverses_id` | El movimiento que corrige un `reversal` |
| `reason` | Obligatorio en los ajustes |
| `seq` | Orden del libro |

- **Cómo se calcula el stock:** el stock de una pieza es `SUM(quantity)` de sus movimientos (RF-94). Como solo se insertan filas, dos salidas simultáneas nunca se pisan (RNF-13).
- **Si sumar empieza a ser lento:** con el volumen de referencia (5.000 piezas) no hace falta caché. Si llegara a hacer falta, se añadiría una tabla `part_stock` actualizada en la misma transacción con `quantity = quantity + :delta`, nunca leyendo y escribiendo. Sería una copia derivada, y la suma de movimientos seguiría mandando.

### Trampas del modelo

- **La numeración de órdenes no puede salir de una secuencia de Postgres.** Una secuencia es global, no por taller y año. Y calcular `MAX(number) + 1` da el mismo número a dos órdenes abiertas a la vez. Se usa `work_order_counters` con una sola sentencia atómica: `INSERT … ON CONFLICT (workshop_id, year) DO UPDATE SET last_number = work_order_counters.last_number + 1 RETURNING last_number`. Pueden quedar huecos si una transacción falla después; para una orden de trabajo es aceptable, porque no es una factura.
- **La matrícula se normaliza al guardar**, no al buscar: `plate_normalized` lleva el índice único, y `plate` conserva lo que se escribió para mostrarlo.
- **Anonimizar no puede romper las FK.** El cliente anonimizado conserva su fila (y su `id`) con los datos personales vaciados; borrarla obligaría a tocar órdenes, presupuestos y movimientos. *Al construirlo (F2):* `POST /workshop/clients/{id}/anonymize` (solo el administrador, `ANONYMIZE_CLIENT`) vacía nombre, teléfono, email, NIF, dirección y notas, archiva al cliente y borra quién trajo el coche en sus órdenes (`dropped_off_by_*`, un nombre y un teléfono). Con una orden abierta, 409: esa orden aún necesita a quién avisar. Sus vehículos siguen a su nombre en el historial; para abrirles una orden hay que cambiar antes el titular. **Anonimizar y abrir una orden se ponen en fila sobre la fila del cliente**: anonimizar pide `FOR UPDATE` antes de contar sus órdenes, y abrir una orden (o darle un vehículo) pide `FOR SHARE` antes de leerlo. El bloqueo de la FK de la orden también espera, pero llega tarde, con el cliente ya leído (comprobado quitando el bloqueo). Una prueba recorre todas las tablas convertidas en texto buscando lo que el cliente era (RNF-40).

## 4. Políticas de RLS

### Roles de base de datos

| Rol | Lo usa | Qué puede |
|---|---|---|
| `axtton_owner` | Las migraciones (Alembic) | Dueño de las tablas. Nunca lo usa la aplicación |
| `axtton_app` | La API y el `worker`, en su camino normal | `NOBYPASSRLS`. Sobre las tablas append-only (`work_order_status_changes`, `quote_decisions`, `stock_movements`, `diagnosis_versions`, `internal_notes`, `audit_log`) solo tiene `SELECT` e `INSERT`: **RNF-12 lo garantiza la base de datos**, no la disciplina del código. Tampoco tiene `DELETE` sobre `clients` (se archivan o se anonimizan, RF-15), `vehicles` ni `vehicle_ownerships` (de esta última solo puede actualizar `ended_at`), ni sobre `work_orders` y `work_order_counters`. De `work_orders` solo puede actualizar lo que cambia con la vida de la orden: el cliente, el vehículo, el número, el año, el tipo y la garantía de origen se fijan al abrirla (*cierre de F2*, migración `0011ordercols`; invariante 7). De `work_entries` solo puede insertar y escribir la anulación (`voided_at`, `voided_by_employee_id`) |
| `axtton_platform` | Solo el código de plataforma (ver "Las vías que cruzan talleres") | `BYPASSRLS`, con una conexión y un pool propios |

Todas las tablas de taller tienen `ENABLE ROW LEVEL SECURITY` y `FORCE ROW LEVEL SECURITY`.

### La política

Es la misma para todas las tablas de taller, generada por una función auxiliar en las migraciones:

```sql
CREATE POLICY workshop_isolation ON <tabla>
    USING (workshop_id = ANY (app_current_workshops()))
    WITH CHECK (workshop_id = ANY (app_current_workshops()));
```

`app_current_workshops()` lee `current_setting('app.workshop_ids', true)` y lo convierte en `uuid[]`. Hay tres casos:

- **Petición normal:** la dependencia del router (§2) abre la transacción con `set_config('app.workshop_ids', '{<taller activo>}', true)`. Es un solo taller: el activo para el personal, o el de su sesión para el cliente.
- **Resumen entre talleres (RF-09):** el conjunto explícito de talleres en los que el usuario es administrador, calculado en el servidor (RNF-09). Es la misma política, sin saltarse nada.
- **Sin valor fijado:** devuelve un array vacío y la consulta **no ve ninguna fila**. Si algo olvida fijar el taller, falla cerrado: no ve datos, nunca los de todos.

La tabla `workshops` tiene la misma política sobre su `id`, para que el personal lea los ajustes de su taller y no los de otro.

### Lo que RLS no cubre

- **RLS separa talleres, no clientes.** Dentro de un taller, que un cliente vea solo sus órdenes lo garantizan los repositorios del portal, que filtran siempre por el `client_id` de la sesión, y las pruebas adversas T4. Llevar el cliente también a RLS obligaría a políticas con joins en cada tabla hija; se registra como riesgo y no se hace.
- **RLS no sustituye a los permisos por rol.** Que un mecánico no envíe presupuestos lo decide la función de permisos (RNF-03).

### Las vías que cruzan talleres

Son exactamente cinco, y todas usan `axtton_platform` desde un único módulo (`app/platform/`). Ningún endpoint de `/workshop` ni de `/portal` lo importa, salvo **dos excepciones con nombre**: el selector de talleres (F1) y la petición de enlace mágico (§7.2, F4). Se escriben, con su fichero y su módulo, en la propia prueba R8 (`R8_EXCEPTIONS`), así que añadir otra es una decisión visible, no un descuido. Hoy `R8_EXCEPTIONS` solo contiene la primera; la segunda se añadirá con el portal.

| Vía | Qué lee | Por qué no puede ir por la política normal |
|---|---|---|
| Endpoints de `/admin` | `workshops`, `users`, `invitations`, `superadmin_invitations`, el `audit_log` de plataforma y **recuentos** por taller (uso respecto a los límites) | El superadministrador no pertenece a ningún taller, y nunca recibe filas operativas (RNF-08), solo números. La aceptación de una invitación de superadministrador (`/api/v1/superadmin-invitations`, pública porque quien acepta aún no tiene cuenta) es parte de esta misma vía: no cruza talleres, solo toca tablas de plataforma |
| Planificador del `worker` | Qué hay pendiente en todos los talleres: avisos por enviar, presupuestos por caducar, firmas por borrar | Tiene que encontrar trabajo sin saber de antemano de qué taller es |
| Comandos de servidor | Crear el primer superadministrador (RF-110), restaurar copias | Operación |
| Petición de enlace mágico (`POST /portal/auth/request-link`, §7.2) | Los pares (taller, cliente) activos con un email | Hay que buscar en todos los talleres antes de saber de cuál es el cliente. Devuelve solo esos pares, que nunca salen en la respuesta |
| Selector de talleres (`GET /workshop/me`, RF-08; añadida en F1) | Los talleres en los que la persona de la sesión es empleada activa, con su nombre y su rol | Hay que saber cuáles son antes de poder fijar ninguno para RLS. Solo devuelve los de la propia persona (`app/platform/memberships.py`) |

El planificador **solo busca** (devuelve ids y su `workshop_id`). Cada trabajo concreto se procesa después **en el contexto de su taller**, con `axtton_app` y la política normal. Así, un fallo en el código que procesa un aviso no puede tocar otro taller.

### Pruebas de RLS

| # | Qué se intenta | Resultado esperado |
|---|---|---|
| R1 | Con `axtton_app`, una consulta sin fijar `app.workshop_ids` | Cero filas en todas las tablas de taller |
| R2 | Fijado el taller A, un `SELECT` sin `WHERE` sobre cada tabla de taller con datos de A y de B | Solo filas de A |
| R3 | Fijado el taller A, `INSERT` de una fila con `workshop_id` de B | Rechazado por `WITH CHECK` |
| R4 | Una tabla de taller nueva sin política | La prueba recorre el catálogo de Postgres (`pg_class`, `pg_policies`) y falla si una tabla con columna `workshop_id` no tiene RLS forzada y la política |
| R5 | `UPDATE` o `DELETE` sobre una tabla append-only con `axtton_app` | Error de permisos |
| R6 | Modificar una línea de un presupuesto enviado, incluso con `axtton_owner` | Lo rechaza el trigger |
| R7 | Dos conexiones del pool: la primera fija el taller A y termina; la segunda reutiliza la conexión sin fijar nada | Cero filas: el valor era de la transacción, no de la conexión |
| R8 | Un endpoint de `/workshop` o `/portal` importa algo de `app/platform/`, salvo las excepciones con nombre | Falla una prueba de arquitectura que lee los imports con el analizador de Python; las excepciones están escritas en la propia prueba (`R8_EXCEPTIONS`) |

## 5. Vista general

```mermaid
flowchart LR
    subgraph Navegador
        TA[App del taller<br/>src/workshop]
        PO[Portal del cliente<br/>src/portal]
    end
    subgraph Servidor
        PX[Proxy<br/>un solo dominio]
        API[api<br/>FastAPI + SDK SuperTokens<br/>+ WeasyPrint]
        WK[worker<br/>SAQ: avisos y tareas programadas]
        ST[supertokens<br/>core]
        STDB[(supertokens-db)]
        DB[(db<br/>Postgres 17 + RLS)]
        VK[(valkey<br/>cola y rate limit)]
    end
    SMTP[[SMTP de la plataforma<br/>Mailpit en desarrollo]]

    TA -- /api/v1/workshop --> PX
    PO -- /api/v1/portal --> PX
    PX --> API
    API --> ST --> STDB
    API -- axtton_app --> DB
    API --> VK
    WK --> VK
    WK -- axtton_app / axtton_platform --> DB
    WK --> SMTP
    API -. enlaces de acceso hasta F5 .-> SMTP
```

- **Un solo dominio**, como en Applications Tracker: el proxy sirve las dos aplicaciones y la API. El taller vive en `/`, el portal en `/portal` y la API en `/api`. Así las cookies de sesión no cruzan dominios y no hace falta CORS en producción.
- **La API no envía avisos al cliente**: los escribe en la bandeja de salida (`notifications`) dentro de la misma transacción que el cambio que los provoca, y el `worker` los envía (§8). Hasta F5, los emails de acceso (invitaciones, enlaces mágicos) los envía la propia API, **después del commit** (en F1, con `BackgroundTasks` de FastAPI): si la transacción fallara, llegaría una invitación a algo que no existe. Para que el commit vaya de verdad antes, la dependencia que abre la transacción del taller se declara con `scope="function"`: con el ámbito por defecto, FastAPI la cierra después de responder y de las tareas en segundo plano (encontrado al cerrar F1).
- **Los PDF los genera la API en el momento** (A14), sin guardarlos.

| # | Decisión | Elección | Alternativa descartada y por qué |
|---|---|---|---|
| A14 | Generación de PDF | **En la API, al pedirlos**, en un hilo aparte (`run_in_threadpool`) y con un tope de generaciones simultáneas para acotar la memoria. No se guardan: se generan desde datos congelados y salen idénticos cada vez (RF-55) | **En el `worker`, como en Applications Tracker**: allí los PDF se guardaban como ficheros; aquí no hay almacén (A9), y encolar para devolver la respuesta en la misma petición añade espera sin aportar nada. **Generarlos al enviar y guardarlos**: obligaría al almacén de ficheros que se ha descartado. **Generarlos en el navegador** (jsPDF, pdfmake, react-pdf): ahorraría CPU del servidor, pero el documento dependería del navegador, sus fuentes y su configuración, y el taller y el cliente podrían tener dos versiones distintas de un presupuesto con valor legal (RF-55). Además, la hoja de recepción y el informe se imprimen y se entregan sin un navegador de por medio, los datos legales cambiarían en tantas copias del frontend como pestañas abiertas, y el portal cargaría cientos de KB de librería para un documento que se abre una vez (RNF-53). Para imprimir pantallas de trabajo sin valor legal (listados, agenda) basta con `window.print()` y CSS de impresión. |

## 6. Estructura del repositorio

Hereda la de Applications Tracker. Lo que cambia es que **la API se parte por actor** y que aparece `platform/`.

```
axtton-core/
├── backend/
│   └── app/
│       ├── api/
│       │   ├── deps.py · rate_limit.py   dependencias comunes (emisor de correo) y límite de peticiones (§2)
│       │   └── v1/
│       │       ├── workshop/        endpoints del personal; el router exige actor staff y valida el taller activo en cada petición (§2)
│       │       ├── portal/          endpoints del cliente; el router exige actor client (marcador hasta F4)
│       │       ├── admin/           endpoints del superadministrador; solo llaman a platform/
│       │       ├── invitations/     rutas sin sesión: aceptar una invitación de empleado o de superadministrador (A5b)
│       │       ├── account.py       contraseña y sesiones; subrouter de /workshop y de /admin
│       │       └── deps.py          las tres dependencias de actor, y nada más decide permisos aquí
│       ├── core/                configuración, SuperTokens, la sesión (sessions.py), BD con el taller fijado, errores
│       ├── domain/              reglas puras: matriz de permisos (can), actores, límite de peticiones, invitaciones;
│       │                        F2 añadió work_orders (transiciones, deshacer), limits, clients, vehicles, search y emails;
│       │                        con F3 llegan totales, días hábiles y estados que ve el cliente (quotes.py y money.py son de F0)
│       ├── models/              SQLAlchemy
│       ├── repositories/        consultas con axtton_app; siempre bajo RLS
│       ├── schemas/             Pydantic, separados por actor cuando lo que se expone difiere
│       ├── services/            casos de uso; commit y rollback
│       ├── platform/            lo único que usa axtton_platform: superadministrador, selector de talleres
│       │                        y, con el worker, el planificador (§4)
│       ├── infra/               módulos detrás de interfaces: email.py, identity.py (SuperTokens), pdf.py,
│       │                        rate_limit.py; la cola llega con el worker
│       ├── scripts/             comandos de servidor (crear superadministrador, reset_data, seed_demo)
│       ├── templates/           hoy solo email/ (la plantilla de la marca); los PDF llegan en F3
│       ├── jobs/                llega con el worker (F5)
│       └── main.py              (worker.py llega en F5)
│   ├── migrations/              Alembic, con el rol axtton_owner
│   └── tests/                   incluidas las adversas T* y R*
├── frontend/
│   └── src/
│       ├── workshop/            la aplicación del personal (features/ por área, lib/ con la sesión y los borradores)
│       ├── portal/              la aplicación del cliente (marcador hasta F4)
│       └── shared/              components/ (shadcn y formularios), lib/ (apiClient, errores, queryClient),
│                                i18n/, styles/
├── .github/workflows/           la CI con el despliegue, el título del PR y release-please (A13)
├── docs/                        MkDocs (este sitio)
├── manual/                      Docusaurus, en F9
├── deploy/                      web/ (Nginx), postgres/ (imagen con los roles) y coolify-deploy.sh (§9)
├── compose.yml                  desarrollo (no hay compose.test.yml: las pruebas usan la base axtton_test del mismo compose)
└── compose.prod.yml             producción en Coolify; compose.prod.local.yml la prueba en local
```

### Reglas de capas

**Backend:** `endpoints → services → repositories → models`, con `domain/` puro. Igual que en Applications Tracker, con tres reglas más:

| Capa | Puede | No puede |
|---|---|---|
| `api/v1/{workshop,portal,admin}/` | Validar con schemas, `Depends`, llamar a **un** service | Consultar la BD, decidir permisos, `commit`, importar de otro prefijo |
| `services/` | Reglas, `domain/`, repositories, `commit`/`rollback`, escribir en la bandeja de avisos | Importar FastAPI, construir SQL, importar `platform/` |
| `repositories/` | Consultas con la sesión de `axtton_app` | `commit`, reglas de negocio, usar `axtton_platform` |
| `platform/` | Usar `axtton_platform`, leer varios talleres | Devolver filas operativas al superadministrador; ser importado desde `api/v1/workshop` o `api/v1/portal`, salvo la petición de enlace mágico (R8) |
| `domain/` | Enums, transiciones, cálculos | Cualquier I/O |

**Regla única:** *si habla con la BD, vive en `repositories/`; si decide, en `services/` o `domain/`; si cruza talleres, en `platform/` y en ningún otro sitio.*

**Frontend:** la estructura por *features* de Applications Tracker, una vez en `workshop/` y otra en `portal/`. **`workshop/` y `portal/` no se importan entre sí**: lo común sube a `shared/`. Una regla de ESLint (`no-restricted-imports`) lo impide.

## 7. Flujos principales

### 7.1 Enviar un presupuesto y que el cliente decida

```mermaid
sequenceDiagram
    actor Ad as Administrador
    participant API
    participant DB
    participant WK as worker
    actor Cl as Cliente

    Ad->>API: POST /workshop/quotes/{id}/send
    API->>DB: BEGIN · fija el taller (RLS)
    API->>DB: SELECT work_order FOR UPDATE
    API->>DB: calcula y guarda totales, reparto del descuento y valid_until
    API->>DB: quote → sent · versión anterior enviada → superseded
    API->>DB: work_order → pendiente_aprobacion (cause = quote_sent, guarda origin_status)
    API->>DB: INSERT notification (dedupe_key = quote_sent:{quote_id})
    API->>DB: COMMIT
    WK->>DB: recoge el aviso pendiente
    WK->>Cl: email con el enlace de acceso a su taller
    Cl->>API: POST /portal/quotes/{id}/decision (approve)
    API->>DB: BEGIN · fija el taller · SELECT work_order FOR UPDATE
    API->>DB: comprueba: es su orden, la versión está en sent y no ha caducado
    API->>DB: INSERT quote_decision (canal portal, IP, navegador)
    API->>DB: quote → approved · work_order → aprobada (cause = quote_decided)
    API->>DB: COMMIT
```

| Paso | Cómo falla | Qué pasa |
|---|---|---|
| Enviar | Otro administrador envió otra versión a la vez | El `FOR UPDATE` serializa los dos envíos. El segundo encuentra la orden en `pendiente_aprobacion` y deja la anterior como `superseded`. El índice único parcial impide dos versiones `sent` aunque el código fallara |
| Enviar | El cliente no tiene email | Se envía igual; la notificación queda como `skipped` y la interfaz lo dice (RF-63) |
| Aviso | El SMTP falla | El `worker` reintenta. Nunca sale dos veces, porque la `dedupe_key` es única y el envío marca la fila antes de enviar (§8) |
| Decidir | El cliente aprueba una versión ya sustituida, caducada o anulada | 409, y el portal muestra la versión vigente |
| Decidir | Dos pestañas del cliente deciden a la vez | La segunda encuentra la versión en `approved` o `rejected`: 409. `quote_decisions.quote_id` es único |
| Decidir | El cliente aprueba un adicional estando la orden en `en_reparacion` | La orden vuelve a su `origin_status` (`en_reparacion`), no a `aprobada` |

**El paso que más se salta:** guardar los totales al enviar. Si se recalculan al mostrar, un cambio en la regla de redondeo o en el IVA de una pieza cambiaría lo que el cliente ya aprobó.

### 7.2 Entrar en el portal con un enlace mágico

```mermaid
sequenceDiagram
    actor Cl as Cliente
    participant PO as Portal
    participant API
    participant ST as SuperTokens
    participant DB

    Cl->>PO: escribe su email
    PO->>API: POST /portal/auth/request-link {email}
    API->>DB: ¿clientes activos con ese email? (vía de plataforma: busca en todos los talleres)
    API->>ST: un código passwordless por cada taller encontrado
    API-->>Cl: un único email con un enlace por taller (si no hay ninguno, no se envía nada)
    API-->>PO: siempre la misma respuesta (RF-41)
    Cl->>PO: abre el enlace del taller A
    PO->>API: POST /portal/auth/consume {código, taller A}
    API->>ST: consume el código (un solo uso)
    API->>DB: fija el taller A · ¿el email es cliente activo de A?
    API->>ST: crea la sesión con actor client, taller A y client_id
    API-->>PO: cookies httpOnly
```

| Paso | Cómo falla | Qué pasa |
|---|---|---|
| Pedir enlace | El email no es cliente de ningún taller | Misma respuesta, mismo tiempo de respuesta aproximado y ningún email |
| Pedir enlace | Alguien pide enlaces en bucle | Límite por email y por IP (§10 de la especificación) |
| Consumir | Se cambia el taller en la URL (T5) | El código se emitió para el taller A: el backend lo comprueba contra lo que guardó al emitirlo y no crea sesión |
| Consumir | El enlace ya se usó o caducó | Error, y el portal ofrece pedir otro |
| Consumir | El cliente fue anonimizado entre pedir y consumir | Ya no es cliente activo: no hay sesión |

**La búsqueda de clientes por email es la única consulta del portal que cruza talleres**, y va por `platform/`. Hay que hacerla antes de saber de qué taller es el cliente. Solo devuelve pares (taller, cliente) y nunca se expone tal cual.

### 7.3 Firmar la hoja de recepción

1. Al abrir la orden se crea `reception_sheets` con los datos de recepción, editables mientras no esté firmada.
2. **Firma en pantalla:** el administrador entrega la tablet y el cliente firma. El navegador envía la firma como SVG, que se limpia en el servidor (solo trazos, sin scripts). En una transacción:
    - se congela `snapshot` (los datos tal cual en ese momento);
    - se guardan la firma, `signed_at` y `signature_method = 'screen'`.
3. **Firma en papel:** el administrador marca la casilla. Se congela igual, con `signature_method = 'paper'` y quién la marcó (RF-52).
4. Desde ahí, el PDF se genera siempre desde `snapshot`. Corregir un dato de recepción cambia la orden y deja constancia en el historial, pero no la hoja.
5. **Plazo de la firma:** un trabajo diario (§8) busca firmas cuyo plazo vence en 30 días y avisa al taller (RF-57). Cuando el plazo vence, borra la firma y deja `signature_purged_at` (RF-56).

| Cómo falla | Qué pasa |
|---|---|
| El SVG trae código o referencias externas | Se rechaza: el servidor reconstruye la firma solo con sus trazos, y el PDF nunca carga nada externo (WeasyPrint con un *fetcher* que solo sirve plantillas, como en Applications Tracker) |
| Se intenta editar una hoja firmada | Lo rechaza un trigger, igual que con los presupuestos |
| La orden se marca "sin presupuesto por renuncia" sin hoja firmada con la renuncia | 409 (RF-27) |

## 8. Trabajo en segundo plano y bandeja de avisos

Hereda el diseño de Applications Tracker (su `segundo-plano.md`), que ya resolvió "nunca dos veces" con fallos reales encontrados en su F12. Lo que cambia aquí es **cómo nacen los avisos**: la mayoría no los descubre un barrido, sino que los escribe el propio cambio que los provoca.

### Cómo nace un aviso

| Origen | Ejemplos | Cómo se crea la fila en `notifications` |
|---|---|---|
| **Un cambio en la aplicación** | Presupuesto enviado o anulado, vehículo listo, otros cambios de estado si el taller los activa (RF-61) | El service la inserta **en la misma transacción** que el cambio. Si el cambio se deshace por error, el aviso también; si el cambio se confirma, el aviso existe seguro |
| **El paso del tiempo** | Recordatorio de cita, ITV o revisión próximas, aviso de firmas a punto de vencer | Un barrido programado la inserta con `INSERT … ON CONFLICT DO NOTHING` sobre la `dedupe_key` |
| **Emails de acceso** | Enlace mágico, invitación, recuperación de contraseña | No pasan por la bandeja: son de la plataforma, no del taller. Desde F5 se encolan **sin el token**: el `worker` genera el enlace al enviar, porque Valkey guarda los trabajos en disco (trampa heredada) |

### Ciclo de vida de una fila

```mermaid
stateDiagram-v2
    [*] --> pending: la crea un cambio o un barrido
    pending --> claimed: el despachador la reclama (scheduled_for ya llegó)
    pending --> cancelled: lo que avisaba cambió (cita movida, titular nuevo, orden cancelada)
    pending --> skipped: el cliente no tiene email o se dio de baja
    claimed --> sent: el servidor SMTP aceptó el mensaje
    claimed --> failed: falló ANTES de entregarlo
    failed --> claimed: reintento (máximo 3, con espera creciente)
    claimed --> unknown: fallo ambiguo o reclamo abandonado
    claimed --> cancelled: al componerlo, lo que avisaba ya no existe
```

La clasificación de fallos es la de Applications Tracker:

| Fallo | Estado | ¿Se reintenta? |
|---|---|---|
| Antes de entregar los datos | `failed` | Sí |
| Después de entregarlos, o el proceso murió a medias | `unknown` | **No**: puede haber salido |

El taller ve en la orden cada aviso y su estado (RF-69).

### Qué es "el mismo motivo" (`dedupe_key`)

| Aviso | `dedupe_key` | Efecto |
|---|---|---|
| Presupuesto enviado | `quote_sent:<quote_id>` | Uno por versión |
| Presupuesto anulado | `quote_cancelled:<quote_id>` | |
| Vehículo listo | `ready:<work_order_id>:<seq del cambio>` | Si se deshace y se vuelve a marcar lista, es otro motivo y se avisa otra vez; reintentar el mismo cambio, nunca |
| Otro cambio de estado (RF-61) | `status:<work_order_id>:<seq>` | |
| Recordatorio de cita | `appointment:<id>:<inicio en segundos UTC>` | Mover la cita es otro motivo. El pendiente de la hora vieja se cancela en la misma transacción que mueve la cita (RF-64) |
| ITV o revisión | `due:<kind>:<vehicle_id>:<client_id>:<fecha>` | Lleva el titular: si cambia, los pendientes del anterior se cancelan (RF-67) y el nuevo titular genera su propio aviso |
| Firmas por vencer (al taller) | `signatures:<workshop_id>:<semana ISO local>` | Un resumen por semana (RF-57) |

**Doble comprobación al enviar.** Aunque se cancele al cambiar, el compositor de cada tipo vuelve a comprobar al enviar que el motivo sigue vigente: la cita sigue a esa hora, el cliente sigue siendo el titular, no se dio de baja. Si no, marca `cancelled` y no envía nada. Cancelar al cambiar es lo rápido; comprobar al enviar es lo que no falla.

### Tareas programadas

Todas son `CronJob` de SAQ. La búsqueda la hace el planificador por `platform/` (§4) y cada elemento se procesa después en el contexto de su taller.

| Tarea | Frecuencia | Qué hace |
|---|---|---|
| Despachador | Cada minuto | Reclama los `pending` cuyo `scheduled_for` ya llegó y encola su envío |
| Reclamos abandonados | Cada 10 minutos | `claimed` de hace más de 10 minutos → `unknown` |
| Citas | Cada 15 minutos | Crea el recordatorio de las citas de mañana, programado a las 10:00 de la hora del taller del día anterior |
| Caducidad de presupuestos | Cada hora | `sent` con `valid_until` vencido → `expired` (la orden no cambia, §6 de la especificación) |
| Vencimientos | Una vez al día por taller, a primera hora local | Crea los avisos de ITV y revisión según la antelación configurada (RF-65) |
| Firmas | Una vez al día | Borra las firmas vencidas (RF-56) y, los lunes, crea el resumen de las que vencen en 30 días (RF-57) |
| Taller de demostración | Una vez al día | Lo recrea con datos ficticios (RF-72), solo si la instalación tiene la demo activada |

**Trampas que se heredan tal cual** (Applications Tracker, `segundo-plano.md`):

- En SAQ, `retries` cuenta **intentos totales**.
- SAQ recuerda la clave de un trabajo terminado unos 10 minutos.
- El mismo envío puede ejecutarse dos veces a la vez: se lee la fila con `FOR UPDATE SKIP LOCKED` y no se suelta hasta marcarla.
- Encolar puede fallar después del commit, así que la fila se queda en `pending` y el despachador la recoge.
- La cola se crea dentro del event loop.
- **Horario de verano:** "a las 10:00 del día anterior" se calcula en la zona del taller con `zoneinfo`, nunca sumando horas a UTC. Lo cubre la prueba B9.

## 9. Entorno y despliegue

### Servicios

| Servicio | Puerto en desarrollo | Para qué | Fase |
|---|---|---|---|
| `db` | 5432 | Postgres 17 de la aplicación, con los tres roles (§4) | F0 |
| `api` | 8000 | FastAPI; `/docs` con el OpenAPI | F0 |
| `frontend` | 5173 | Vite con las dos entradas (`/` y `/portal`) | F0 |
| `supertokens` + `supertokens-db` | — | Core de autenticación y su propio Postgres; sin puertos publicados | F1 |
| `valkey` | — | Límites de peticiones (RNF-06, F1); la cola de SAQ llega con el `worker` (F5) | F1 |
| `worker` | — | La misma imagen que `api` con otro comando | F5 (antes, sin trabajos) |
| `mailpit` | 8025 | Solo desarrollo: captura todo el correo | F1 |
| `web` | — (8080 solo al probar producción en local) | Solo en `compose.prod.yml`: Nginx con las dos aplicaciones compiladas y el reenvío de `/api` | F2 |
| `docs` | 8001 | MkDocs | F0 |
| `manual` | 3001 | Docusaurus | F9 |

- **Un comando** levanta todo: `docker compose up --build` (RNF-30).
- **Siempre `localhost`, nunca `127.0.0.1`:** para el navegador son sitios distintos y la cookie de sesión no viaja (trampa heredada).

### Los tres roles de la base de datos

Se crean con un script de inicio de Postgres (`docker-entrypoint-initdb.d`), y las contraseñas llegan por variables de entorno.

> **Trampa:** esos scripts **solo se ejecutan con el volumen vacío**. Los roles no se pueden crear también en una migración, porque las migraciones corren como `axtton_owner` y solo un superusuario puede crear un rol con `BYPASSRLS` ([decisión 0001](../decisiones/0001-roles-solo-en-el-script-de-inicio.md)). En desarrollo, cambiar el script obliga a `docker compose down -v`; en producción, un rol nuevo es un paso manual con el superusuario.

### Producción (desde F2)

Como en Applications Tracker (su decisión 0023). Construido en F2 ([decisión 0004](../decisiones/0004-produccion-en-coolify.md), [guía](../guias/despliegue.md)): `compose.prod.yml`, `deploy/web/` (Nginx), `deploy/postgres/` (los roles dentro de la imagen) y el job `deploy` de la CI.

- **Coolify con un solo dominio:**
  - un servicio `web` (el proxy) sirve las dos aplicaciones ya compiladas y reenvía `/api` a la API. Cada aplicación necesita su propio *fallback*: las rutas `/portal/*` que no son ficheros sirven `portal/index.html`, y el resto, `index.html` (lo aprendido en F0; en desarrollo lo hace el plugin `portalFallback` de Vite);
  - solo `web` tiene dominio público;
  - el resto de servicios no publica puertos.
- **Despliegue continuo:** cada push a la rama principal, con la CI en verde, despliega. Lo pide el job `deploy` de la CI a la API de Coolify; el *Auto Deploy* de Coolify está desactivado, porque desplegaría aunque la CI fallara.
- **Versión** (*decidido antes del primer despliegue, F2*; [decisión 0003](../decisiones/0003-versionado-por-etiquetas-y-release-please.md)): la imagen se construye con la última etiqueta `vX.Y.Z` y el commit (`APP_VERSION`, `APP_COMMIT`; `VITE_APP_*` para el frontend), y `GET /api/v1/meta` los responde. El despliegue comprueba ahí que arrancó lo que acaba de construir. Una versión se publica aparte, al fusionar el PR de release-please, y no cambia el contrato `/api/v1` ([guía](../guias/versionado.md)).
- **`APP_URL`**: la dirección pública del frontend. La API la usa para construir los enlaces que recibe el cliente, que apuntan a páginas del portal y no a la API (lo aprendido en F0).
- **Copias de seguridad:** un servicio de copias diarias fuera del servidor desde F9 (RNF-33), y la restauración se prueba antes de cerrar la fase.
- **La demo** (*decidido antes del primer despliegue, F2*; hoy es la única instalación, en `axtton.imigueldev.duckdns.org`, y sin correo): una instalación aparte, con `DEMO_SEED_ENABLED=true`, que cada noche ejecuta `python -m app.scripts.seed_demo --purge-other-accounts` (una tarea programada de Coolify). Vacía los datos, borra las cuentas que hayan creado los visitantes y vuelve a cargar los dos talleres de ejemplo con fechas relativas a ese día ([guía](../guias/demo.md)). Una instalación real no tiene la variable, y el script se niega a correr.

## 10. Pruebas

| Nivel | Qué cubre | Dónde corre |
|---|---|---|
| `domain/` | Transiciones de la orden y del presupuesto, cálculo de totales y redondeo (RNF-14), reparto del descuento global, días hábiles, matriz de permisos, estados que ve el cliente | Sin base de datos; el más rápido |
| Repositorios | Consultas, **siempre contra Postgres real con los roles reales** y RLS activa (nunca SQLite: RLS, `EXCLUDE` y los triggers no existirían) | La base `axtton_test` del compose (aún no hay `compose.test.yml`) |
| Services | Casos de uso, concurrencia con dos transacciones reales (carreras de §7), bandeja de avisos | Ídem |
| API | Contrato y adversas: T1–T11 (actores), R1–R8 (RLS), B1–B12 (avisos, adaptadas de Applications Tracker) | Ídem |
| Migraciones | Subir y bajar contra una base **con datos** (RNF-35) | CI |
| Frontend | Componentes y hooks con vitest; la regla de imports entre `workshop/` y `portal/` | CI |
| Punta a punta | El flujo de los criterios de éxito (cita → recepción → presupuesto → aprobación en el portal → entrega), con Playwright | CI desde F6; antes, a mano |
| Rendimiento | RNF-50 a RNF-53 con el volumen de referencia (un script que lo genera) | A mano, antes de cerrar F9; no en cada CI |

**Las pruebas adversas se escriben con la funcionalidad, no al final.** Un endpoint nuevo en `/workshop` queda cubierto por T1 y T2 automáticamente porque recorren el OpenAPI, y una tabla nueva, por R4 porque recorre el catálogo de Postgres.

## 11. Orden de implementación

| Fase | Qué se construye, en concreto |
|---|---|
| **F0** ✔ | **Hecha** ([cierre y lo aprendido](f0-cierre.md)). Esqueleto vertical desechable: `workshops`, `clients`, `vehicles`, `work_orders`, `quotes` y `quote_lines` mínimos; un taller fijo; enviar un presupuesto de una línea, aprobarlo desde un enlace secreto y ver el cambio de estado. **Incluye un primer RLS de verdad** (dos roles y una política) y un PDF de una página, porque son lo que más puede sorprender. Se tira al terminar |
| **F1** ✔ | Roles de BD y política generada por migración; R1–R5, R7 y R8 (R6 espera a los triggers de presupuesto, F3). SuperTokens con `emailpassword`, los tres routers y sus dependencias; T1–T3. `users`, `employees`, `invitations`, superadministrador por comando, alta de talleres, modo de instalación, taller activo. `audit_log`. Mailpit. **CI**. *Añadido al construirlo:* límite de peticiones con Valkey (RNF-06), cuenta del personal (cambio de contraseña y sesiones), consulta del registro de auditoría e invitación de otros superadministradores (RF-110) |
| **F2** | Clientes, vehículos, `vehicle_ownerships`, órdenes con su historial, número correlativo, deshacer, búsqueda, bloqueo optimista, borradores en IndexedDB. *Añadido al planificarla:* diagnóstico, notas internas y trabajos (RF-22, RF-23: lo que guardan los borradores), cobro (RF-28, RF-29) y anonimización (RF-15), y una revisión del diseño de la interfaz validada **antes** del despliegue. **Primer despliegue en Coolify** |
| **F3** | Datos del taller y `labor_rates` editables por su administrador (RF-02; `axtton_app` recibe `UPDATE` solo sobre esas columnas de `workshops`, migración `0003grants`), presupuestos versionados con sus triggers, totales y descuentos, decisión registrada por el taller, PDF del presupuesto con los datos legales |
| **F4** | Receta `passwordless`, petición y consumo del enlace por taller (§7.2), routers del portal, estados para el cliente, aprobación desde el portal; T4–T7 |
| **F5** | `worker`, bandeja de avisos, despachador, presupuesto enviado y vehículo listo; B1–B6 |
| **F6** | Hoja de recepción con firma (§7.3), resumen de entrega, informe de actuaciones, descarga en el portal; prueba de punta a punta en CI |
| **F7** | Catálogo, `stock_movements`, `used_parts`, líneas desde el catálogo, unidades comprometidas |
| **F8** | Citas y su conversión en orden, recordatorios, vencimientos, borrado de firmas con su aviso; B7–B11 |
| **F9** | Resumen entre talleres, exportaciones, datos de demostración, copias de seguridad con restauración probada, prueba de rendimiento, manual |

## 12. Riesgos de esta arquitectura

| Riesgo | Mitigación |
|---|---|
| **RLS mal configurada que no falla, sino que deja pasar todo** (la aplicación conectada como dueña, una tabla sin `FORCE`) | R1, R4 y R7 en CI desde F1. Si RLS se desactiva por error, las pruebas lo detectan aunque ninguna funcionalidad falle |
| **Rendimiento de RLS**: la política se evalúa por fila | La función `app_current_workshops()` es `STABLE` y todos los índices empiezan por `workshop_id`. Se mide con el volumen de referencia (§10) | *Descubierto en F2 (búsqueda, RF-14):* bajo RLS, Postgres solo usa un índice para una condición cuyo operador es `LEAKPROOF`. `=` lo es, así que el índice por `workshop_id` siempre lleva a las filas del taller; `LIKE` no lo es, así que un "contiene" recorre las filas del taller y ningún índice trigram lo acelera. Medido con 20.000 clientes en un taller: 28 ms (0,36 ms con trigram y sin RLS). Cumple RNF-51 de sobra; si algún día no bastara, la salida no es marcar `LIKE` como `LEAKPROOF` (necesita superusuario y es una decisión de seguridad), sino otra estructura de búsqueda. `test_search.py` vigila que nunca se recorran filas de otros talleres.
| **Personalizar la receta passwordless** para ligar el enlace a un taller (§7.2) es lo menos conocido del diseño | Se prueba al principio de F4 con un esqueleto de esa parte antes de construir el portal. Si SuperTokens no lo permite limpiamente, el plan B es guardar el taller junto al código emitido en nuestra propia tabla |
| **Borradores en una tablet compartida**: el borrador de un mecánico lo vería el siguiente | Los borradores se guardan por usuario y taller, y se borran al cerrar sesión. *Al construirlo en F2:* se borran **antes** de cerrar la sesión, no en el evento de SuperTokens (la navegación al login podría cortar el borrado); si la sesión solo caduca, se conservan para quien vuelva a entrar, y al iniciar sesión se borran los de cualquier otra persona |
| **Reenviar un borrador duplica lo anotado**: la nota llegó, pero la respuesta se perdió con la conexión | *Descubierto al construirlo en F2:* la nota y el trabajo llevan un id que genera el navegador al empezar el borrador. El reenvío encuentra la fila ya guardada y responde como si la guardara (misma orden y mismo autor; si no, 409 `id_in_use`); dos reenvíos a la vez los para la clave primaria (409 `already_saved`, que el navegador toma por guardado). Si se edita lo pendiente, lleva otro id: con el mismo, el cambio se perdería en silencio. El diagnóstico no lo necesita: su bloqueo optimista ya convierte el reenvío en el aviso de RNF-15 |
| **WeasyPrint en la API** consume memoria y CPU en cada descarga | Generación en un hilo con un tope de simultáneas (A14); si no basta, se pasa al `worker` sin cambiar la API |
| **La firma en SVG** es una puerta para inyectar contenido | El servidor reconstruye la firma solo con sus trazos (§7.3) y el PDF no carga nada externo |
| **Entregabilidad del correo de la plataforma**: si los emails acaban en spam, el portal pierde su sentido | SPF, DKIM y DMARC del dominio de la plataforma en el manual de despliegue (F9). El estado de cada aviso es visible en la orden (RF-69) |
| **Sobreingeniería**: tres roles de BD, tres actores, versionado, bandeja de avisos | Cada pieza responde a un requisito numerado. Lo que no lo hace no entra sin pasar por la bitácora de decisiones (R1 de la especificación) |
