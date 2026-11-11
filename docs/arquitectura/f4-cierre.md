# Cierre de F4: lo aprendido

> Fase cerrada el 2026-11-11. Commits `f1b03cc` a `899a6ba`, más el PR del cierre. Como en F2 y F3, cada paso llegó a producción al fusionarse; la entrada del portal sin correo de la demo necesita además `DEMO_PORTAL_ENTRY=true` en su instalación de Coolify ([guía de la demo](../guias/demo.md#el-portal-del-cliente)).

F4 era **el portal del cliente** (especificación §9): que el cliente siga su reparación y responda a sus presupuestos sin llamar al taller. Lo difícil no era la pantalla, sino tres cosas que RLS no resuelve sola: entrar sin contraseña en un taller concreto aunque el mismo email sea cliente de otros, que dentro de un taller un cliente nunca vea lo de otro, y que lo que el cliente decide valga como prueba sin dejar sus datos para siempre.

Lo construido, en nueve pasos:

1. El enlace mágico propio, pedido desde la entrada de cada taller y ligado a él: un token guardado como hash, de 15 minutos y un solo uso ([decisión 0006](../decisiones/0006-enlaces-magicos-propios-ligados-al-taller.md), RF-40, RF-41, migración `0016portallinks`).
2. La sesión del cliente: 30 días, y una cerradura (`clients.portal_epoch`) que la corta al instante al cambiar el email o anonimizar; revocar solo las de ese taller y ese cliente, y borrar su usuario de SuperTokens si no le queda ninguna (RF-47, T7, migración `0017portalepoch`).
3. Los estados que ve el cliente, que no son los internos, y el aviso de fecha de entrega pasada (`domain/portal.py::client_progress`, RF-80).
4. Sus vehículos y sus órdenes: diagnóstico vigente, versiones enviadas del presupuesto y trabajos sin anular, siempre por `work_orders.client_id` (RF-42 a RF-44, T4).
5. Aceptar o rechazar desde el portal, con la IP y el navegador, y el borrado de lo personal de esa decisión al anonimizar (RF-34, RF-36, RNF-40, migración `0018decisionerase`).
6. El PDF de cada versión para el cliente, el mismo que el del taller sin el motivo de una anulación ni quién anotó la decisión (RF-54).
7. Lo que el taller ve del portal: su dirección corta `/portal/{nombre}`, el logotipo en la entrada, el límite de las páginas sin sesión y la IP de las decisiones para el administrador ([decisión 0007](../decisiones/0007-nombre-corto-del-taller-en-el-portal.md), migración `0019portalslug`).
8. El portal en la demo: nombres cortos, una aprobación desde el portal y la entrada sin correo como un cliente de la demo.
9. El cierre.

Y el cierre: qa-verifier y docs-writer contra todo lo anterior, con lo que encontraron ya corregido (ver abajo). Al terminar, **1.111 pruebas** contra Postgres, SuperTokens y Valkey reales.

## Lo que se confirmó

| Idea del diseño | Cómo se comprobó |
|---|---|
| Ninguna consulta del portal cruza talleres salvo las que tienen nombre | La entrada lleva siempre el taller y busca bajo RLS. La única excepción es buscar un taller por su nombre corto, por la vía de plataforma, y R8 la nombra. Al cierre, `test_adverse_f4.py` comprueba que esa vía solo responde a un nombre exacto de un taller activo y que, con un taller fijado, `axtton_app` no ve el nombre de otro |
| RLS no separa a los clientes de un taller, y eso lo hace el código | `repositories/portal.py` exige el `client_id` de la sesión en las consultas de entrada. Al cierre, un barrido recorre **todas** las rutas del portal con un id, leídas del OpenAPI, con tres ataques: otro cliente del taller, el mismo email en otro taller y al revés. Todos dan el mismo 404 que un id que no existe, sin cambiar nada. Una ruta nueva queda cubierta sola |
| Lo que sale por el portal se elige campo a campo | Ningún esquema del taller se reutiliza. Al cierre, un barrido junta todas las respuestas y los dos PDF y busca en ellas los nombres del personal, las notas internas, las horas, el motivo de la anulación y la nota de la decisión |
| Un enlace sirve una sola vez | Cerrarlo es una sentencia que comprueba y escribe a la vez. Con dos transacciones reales, el segundo uso espera y lo encuentra cerrado (T6) |
| Una sesión deja de valer al instante, no cuando caduque su token | La cerradura se compara en cada petición. Revocar sesiones por sí solo dejaba 5 minutos de margen y no veía una sesión creada justo después (T7) |
| La decisión vale para la versión que vio el cliente | Se ata por el id de la versión. Una sustituida, anulada, caducada o ya decidida da 409, también con dos pestañas, con el cliente y el taller a la vez, o mientras el taller renueva |
| Lo decidido no cambia, y lo personal se borra (invariante 6, RNF-40) | El trigger solo deja vaciar la IP, el navegador y el motivo, y solo con el cliente ya anonimizado, probado con los tres roles. Al cierre, de punta a punta: el cliente entra, rechaza con motivo, se le entrega el coche y se le anonimiza. No queda ningún dato suyo en ninguna tabla ni su usuario en SuperTokens |
| Cada guarda tiene una prueba que la vigila | En cada paso se rompió el código a propósito (9, 12, 6, 10 y 5 maneras) y al cierre otras 17. En todos los casos falló alguna prueba |

## Lo que se descubrió

| Descubrimiento | Por qué importa | Dónde ha quedado |
|---|---|---|
| **Consumir un código `passwordless` de SuperTokens borra todos los del mismo email** | Con un enlace por taller, abrir el de A inutilizaba el de B. Era el riesgo principal de la arquitectura (§12) | Enlaces propios en `portal_links`; de la receta solo `signinup`. [Decisión 0006](../decisiones/0006-enlaces-magicos-propios-ligados-al-taller.md) |
| **Un email con un enlace por taller** no escala, y buscar el email en todos los talleres cruzaba talleres desde el portal | Con muchos talleres, un correo inutilizable y una vía de plataforma más | El enlace se pide desde la entrada de cada taller (decisión 0006, cambia RF-45 y R3) |
| **Un 401 del portal renovaba la sesión en bucle** | El navegador, ante un 401, renueva y repite la petición, que vuelve a dar 401 | `end_session` en la dependencia del portal; lo que se puede reactivar va con 403 |
| **La duración de las sesiones de SuperTokens es global** | Los 30 días del cliente no se pueden configurar en el core sin cambiar los del personal | `portal_expires_at` en la sesión, comprobado en cada petición |
| **Lo que decide el cliente es prueba, pero también un dato personal** | RF-36 obliga a guardar la IP y el navegador, y RNF-40 a no dejar ningún dato tras anonimizar; las decisiones no se tocaban ni por SQL | Decidido por el usuario: al anonimizar se vacían esos tres datos y se conserva lo decidido. Excepción con nombre en el invariante 6 (`0018decisionerase`) |
| **El motivo del cliente no puede ir al historial de la orden** | El historial es append-only y nadie puede vaciarlo | Se queda solo en la decisión |
| **`request_ip` puede dar "unknown"** | La columna INET lo rechazaba con un 500 justo al aprobar | `core/client_ip.py::valid_ip`: si no es una IP, se guarda vacía |
| **Una dirección corta no se puede resolver sin mirar todos los talleres** | `/portal/{nombre}` no dice de qué taller es | Una vía de plataforma acotada y una decisión nueva ([0007](../decisiones/0007-nombre-corto-del-taller-en-el-portal.md)) |
| **La demo desplegada no tiene correo** | Ningún visitante recibiría el enlace | Decidido por el usuario: con `DEMO_PORTAL_ENTRY`, un botón por cliente de la demo que emite y consume un enlace de verdad |
| **Entrar en otro taller mientras se cierran las sesiones de uno podía cerrar también la nueva**: `revoke_client_sessions` decidía borrar el usuario con la lista leída antes. Lo encontró qa-verifier | T7 dice que la sesión del otro taller sigue viva | Se vuelven a leer las sesiones justo antes de borrar. La ventana que queda está en "Lo que queda abierto" |
| **Romper el código a propósito cambia también la API local**, que recarga el mismo código | Mientras faltaba una guarda, una prueba a mano en el navegador guardó un nombre reservado en la base de desarrollo | Las pruebas a mano esperan a que terminen las mutaciones |
| **Una búsqueda de "7.25" en el texto de una respuesta acertaba a veces dentro de una fecha** (los segundos de `…:57.254`) | La prueba de fugas fallaba de vez en cuando sin ninguna fuga | Se busca como número suelto |

## Qué cambió respecto al diseño

- **RF-45 y R3**: el cliente de varios talleres entra en cada uno desde su dirección, no con un correo con un enlace por taller (decisión 0006).
- **Las vías que cruzan talleres son cinco**: se añade la del nombre corto (decisión 0007, arquitectura §4).
- **El logotipo sale también en la entrada del portal** (la decisión 0005 decía que no).
- **El invariante 6 tiene una excepción con nombre**: vaciar la IP, el navegador y el motivo de una decisión del portal al anonimizar.
- **El PDF del cliente no es idéntico al del taller** cuando hay un motivo de anulación o un empleado que anotó la decisión; sin ellos, sí lo es.
- **La IP y el navegador de una decisión los ve solo el administrador** (fila nueva en la matriz de permisos).
- **Dos límites nuevos**: 60 por minuto por IP en las páginas sin sesión y 20 PDF cada 10 minutos por cliente.

## Lo que queda abierto

| Tema | Estado |
|---|---|
| Los correos con enlace al portal (presupuesto enviado, vehículo listo) y la marca `expired` escrita | Con el worker, en F5. Hasta entonces el cliente entra desde la dirección de su taller |
| Borrar las filas viejas de `portal_links` | Una tarea programada del worker (F5) |
| Las citas en el portal (RF-46) | Con las citas, en F8 |
| La hoja de recepción y el resumen de entrega en el portal (resto de RF-54) | F6 |
| **La ventana que queda en T7**: entre la última lectura de las sesiones y el borrado del usuario, o entre el `signinup` y la sesión nueva de otro taller | Solo obliga a ese cliente a volver a entrar; no se pierde ni se filtra nada |
| **El límite de peticiones guarda el email en una clave de Valkey** hasta una hora | Fuera del barrido de RNF-40, que mira la base de datos. Caduca sola; si hiciera falta, anonimizar podría borrarla |
| Los clientes que ofrece la demo son los cuatro primeros por nombre | Transportes Navarro, que aprobó desde el portal, no está entre ellos |
| Migraciones arriba y abajo con datos (RNF-35) | Sin probar todavía, como al cierre de F3 |

## Riesgos que F4 ha reducido y los que siguen abiertos

- **Reducidos:** el riesgo principal de la arquitectura, el enlace mágico con la receta `passwordless`, quedó resuelto al empezar la fase con un enlace propio (decisión 0006). También, que un cliente vea lo de otro (barrido T4 de todas las rutas), que una sesión robada o vieja siga valiendo (la cerradura y los 30 días) y que una decisión del portal se aplique a una versión que el cliente no vio.
- **El siguiente riesgo grande** es el worker (F5): que cada aviso salga una sola vez aunque el mismo envío se ejecute dos veces a la vez, en la transacción del cambio que lo provoca (invariante 8).
