# Cierre de F1: lo aprendido

> Fase cerrada el 2026-10-26. Commits `98c2c6e` a `b966ae4`, más el commit del cierre.

F1 era **lo más caro de añadir tarde** (especificación §11): quién entra, en qué taller y con qué permisos, y que la base de datos impida mezclar talleres pase lo que pase en el código. Todo lo que venga después se construye encima.

Lo construido, en ocho pasos:

1. Lo desechable de F0 retirado y la migración inicial definitiva, con RLS en toda tabla de taller ([decisión 0002](../decisiones/0002-historial-de-migraciones-desde-f1.md)).
2. SuperTokens con los tres actores y sus tres prefijos de API, cerrados entre sí, y sin registro público.
3. El superadministrador por comando y el alta de talleres con invitación al primer administrador.
4. Invitaciones de empleados, el taller activo validado en cada petición, empleados y roles con la matriz de permisos.
5. La cuenta (recuperar y cambiar la contraseña, sesiones), la CI y todas las pantallas, en español e inglés.
6. El límite de peticiones con Valkey (RNF-06).
7. La consulta del registro de auditoría, del taller y de la plataforma (RNF-16).
8. Invitar a otros superadministradores desde la aplicación (RF-110).

Y el cierre: qa-verifier y docs-writer contra todo lo anterior, con lo que encontraron ya corregido. Al terminar, **189 pruebas** contra Postgres, SuperTokens y Valkey reales.

## Lo que se confirmó

| Idea del diseño | Cómo se comprobó |
|---|---|
| RLS aísla **cada** tabla de taller, no solo las que se probaron a mano | `test_rls_tables.py` siembra dos talleres en todas y comprueba, tabla a tabla, lectura, escritura, `UPDATE` y `DELETE` cruzados. Un control falla si aparece una tabla con `workshop_id` que no esté en la lista |
| Cada prefijo rechaza a los otros dos actores | T1 y T2 leen las rutas del OpenAPI: una ruta nueva queda cubierta sola. Las de esta fase (`/admin/superadmins`, `/admin/audit`, `/workshop/audit`) entraron sin tocar la prueba |
| El actor no se puede cambiar desde fuera | T9: un token con el actor editado a mano da 401, no 403 (la firma ya no coincide). T11: solo `app/core/sessions.py` escribe el contenido de una sesión |
| El taller activo se valida en cada petición | Quitar el acceso o desactivar un taller corta al instante, con la sesión abierta |
| El registro de auditoría es append-only por permisos | `UPDATE`, `DELETE` y `TRUNCATE` rechazados para `axtton_app` y `axtton_platform` |
| Las capas se respetan | `test_architecture.py` lee los imports: un service que importe FastAPI o `app.platform` rompe la CI. R8, igual para `/workshop` y `/portal` |
| Cada guarda tiene una prueba que de verdad la vigila | Se rompió a propósito cada una (el middleware del límite, la normalización de sus rutas, el filtro de la auditoría de plataforma, el rechazo de una cuenta de personal como superadministrador) y su prueba falló |

## Lo que se descubrió

| Descubrimiento | Por qué importa | Dónde ha quedado |
|---|---|---|
| **El commit llegaba después de la respuesta.** Con el ámbito por defecto de FastAPI, la salida de una dependencia con `yield` se ejecuta tras enviar la respuesta y tras las `BackgroundTasks` | Un 2xx podía no estar guardado, y el email de invitación salía antes que su invitación. La trampa de CLAUDE.md afirmaba justo lo contrario. Lo encontró qa-verifier | `Depends(..., scope="function")` en `ActiveWorkshop` e `InvitationSession`; `test_commit_order.py`; CLAUDE.md y arquitectura §5 |
| **Comprobar un recuento no basta con READ COMMITTED.** Dos administradores que se quitaban el rol a la vez dejaban el taller sin ninguno; dos aceptaciones con un solo hueco entraban las dos; en taller único, dos altas creaban dos talleres | La regla estaba bien escrita y probada, pero solo con una transacción cada vez | Bloqueo consultivo por taller (`lock_staff`) y por alta; `test_concurrency.py` intercala dos transacciones reales |
| **Los privilegios por defecto del dueño daban de más.** `axtton_app` podía hacer `UPDATE users SET kind = 'superadmin'` (`users` no tiene RLS), cambiar el estado y los límites de su taller y tocar `alembic_version` | Un fallo en `/workshop` habría bastado para crear un superadministrador | Migración `0003grants`; prueba en `test_rls_tables.py`; CLAUDE.md |
| **SuperTokens responde "¿existe este email?"** en rutas públicas que no sirven para nada sin registro | Anulaba el "responde igual" de la recuperación de contraseña (RF-121) | Operación desactivada en `core/supertokens.py`; `test_adverse_f1.py` |
| **El actor se escribe mejor enganchándose a SuperTokens** (`create_new_session`) que con una función propia | Todas las recetas pasan por ahí: no queda ninguna vía para crear una sesión sin actor | Arquitectura §2 |
| **Las rutas de SuperTokens no admiten dependencias de FastAPI**, y responden en varias formas equivalentes | El límite de peticiones tiene que ser un middleware, por fuera del suyo, que reconozca `/signin/`, `/public/signin` y `;x` | `app/api/rate_limit.py`; arquitectura §2 |
| **El SDK del navegador lanza la propia `Response`** ante un 429, y la caché cacheaba "sin sesión" antes del login | Sin tratarlo, el 429 era un error genérico y entrar devolvía al login | `errors.ts` y `supertokens.ts`; CLAUDE.md |
| **Un `null` explícito en un campo obligatorio daba 500** | Pydantic lo aceptaba como "no lo cambies" y la base de datos lo rechazaba | Validador en `EmployeeUpdate` |
| **La CI corre en Linux**: los `.sh` necesitan el permiso de ejecución en git, y el código montado no es del usuario de la API | En Windows nada de eso se nota | CLAUDE.md, trampas |
| **El backend rechaza emails de dominios reservados** (`.local`) | Un 422 sin código parecía un fallo del sistema | `errors.invalid_input`; para pruebas, `@example.com` |

## Qué cambió respecto al diseño

- **El límite de peticiones** quedó más estricto que en la especificación (§10), con valores "de partida" en `domain/rate_limits.py`, y se añadieron reglas que el diseño no tenía: aceptar una invitación por enlace (aceptar con una cuenta existente exige su contraseña) y cambiar la contraseña por usuario.
- **La auditoría** se consulta desde F1, no solo se escribe, y la de plataforma es la de `workshop_id` nulo.
- **Las invitaciones de superadministrador** tienen su propia tabla de plataforma, sin RLS y sin ningún permiso para `axtton_app`, y su propia ruta pública. No es una excepción de R8: no cruza talleres.
- **`audit_log` no lleva `UNIQUE (id, workshop_id)`**: nadie la referencia y su `workshop_id` puede ser nulo (arquitectura §3).

## Lo que queda abierto

| Tema | Estado |
|---|---|
| **RF-114 dice que el listado de talleres muestra sus administradores**, y hoy muestra recuentos (`test_admin.py` comprueba que no salen nombres) | Por decidir: o se añaden los nombres, o la especificación se queda en recuentos |
| **RF-02**: el administrador edita los datos de su taller, el logotipo y las tarifas de mano de obra | Sin construir y sin fase asignada. Necesita datos legales para el PDF (F3); cuando llegue, `axtton_app` recibe `UPDATE` solo sobre esas columnas de `workshops` |
| Migraciones arriba y abajo **con datos** (RNF-35) y un arranque con volúmenes vacíos en la CI | Sin probar todavía |
| T4–T7 y T10 (cliente) | Llegan con el portal, en F4 |
| El rechazo de un access token caducado | Solo se ha probado el de un token alterado |

## Riesgos que F1 ha reducido y los que siguen abiertos

- **Reducidos:** el aislamiento entre talleres (ahora probado en todas las tablas y con permisos mínimos), los tres actores, las carreras sobre recuentos y el orden commit–respuesta–email. Lo que en F0 era un patrón ahora es la base, con sus pruebas adversas en la CI.
- **Sigue abierto, y sigue siendo el siguiente riesgo grande:** el enlace mágico ligado a un taller con la receta `passwordless` (arquitectura §12). Se prueba al principio de F4.
- **Nuevo a vigilar:** el bloqueo consultivo pone en fila los cambios del personal de un taller. Con pocos empleados por taller no se nota; si apareciera contención, se notaría primero en las aceptaciones de invitaciones.
