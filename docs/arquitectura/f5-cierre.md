# Cierre de F5: lo aprendido

> Fase cerrada el 2026-11-17. Commits `f8aef7d` a `e6e273c`, más el PR del cierre. Cada paso llegó a producción al fusionarse; el `worker` corre en Coolify desde el paso 1 (con el arreglo `1b8ffdd`). La demo desplegada no tiene correo, así que allí los avisos acaban "no enviados" con ese motivo.

F5 era **el trabajo en segundo plano y los avisos al cliente** (especificación §9): que el cliente se entere por correo de su presupuesto y de que su coche está listo, sin que la API tenga que esperar a un servidor de correo. Lo difícil no era enviar un correo, sino el invariante 8: que cada aviso nazca con el cambio que lo provoca y **no salga dos veces** aunque el mismo envío se ejecute dos veces a la vez, el proceso muera a mitad o el servidor se corte con el mensaje en vuelo.

Lo construido, en nueve pasos:

1. El `worker` de SAQ sobre Valkey, con la misma imagen que la API; el planificador que solo busca qué talleres tienen trabajo, y su primera tarea: borrar los enlaces del portal caducados (`0020linkpurge`).
2. Los presupuestos fuera de plazo, escritos como `expired` cada hora, con un trigger que impide marcar uno que aún vale (RF-33, `0021quoteexpiry`).
3. El envío SMTP paso a paso, que sabe si el correo no salió (se puede reintentar) o si no se sabe (no se reintenta), con cifrado que nunca se rebaja y el Reply-To del taller (RF-68).
4. La bandeja de avisos: `notifications` con RLS y una clave por motivo, el despachador, el envío con la fila bloqueada, los reintentos y los reclamos abandonados (RF-62, B1–B6, `0022outbox`).
5. Los avisos de presupuesto enviado y anulado, en el idioma del cliente, con el botón a su orden en el portal (RF-60, [decisión 0008](../decisiones/0008-el-boton-de-un-aviso-no-es-un-enlace-magico.md)).
6. El aviso de vehículo listo, ligado al cambio de estado que la puso lista (RF-60).
7. Lo que ve el taller: la pestaña "Avisos" de la orden y el aviso, antes de actuar, de que el cliente no tiene email (RF-63, RF-69).
8. El enlace mágico del portal, emitido y enviado por el worker, con reintentos (RF-40, RF-41).
9. El cierre: los avisos de la demo con la fecha de su motivo, y qa-verifier y docs-writer contra todo lo anterior, con lo que encontraron ya corregido (ver abajo).

Al terminar, **1.360 pruebas** contra Postgres, SuperTokens y Valkey reales.

## Lo que se confirmó

| Idea del diseño | Cómo se comprobó |
|---|---|
| "Nunca dos veces" son varias guardas, no una | Cada una tiene su prueba y se rompió a propósito: el índice único de la clave, el reclamo con `FOR UPDATE SKIP LOCKED`, la fila bloqueada durante la conversación SMTP, el trabajo que no hace nada si el aviso ya no está reclamado con su intento, y el trigger que hace finales `sent` y `unknown`. Al cierre, otras tantas roturas (72 sentencias con los triggers anulados, la RLS abierta, sin `SKIP LOCKED`, sin volver a mirar al caducar) hicieron fallar alguna prueba |
| El aviso nace en la transacción del cambio (invariante 8) | Un cambio que se deshace no deja aviso; crear el mismo motivo dos veces, ni siquiera a la vez, deja una sola fila |
| Lo que va en el correo se escribe al enviar, no al crear | La fila no guarda ni el email ni el texto. Cada compositor vuelve a mirar el motivo: una versión corregida antes de salir su aviso solo avisa de la nueva, y un coche entregado antes de salir el "listo" no avisa |
| Un fallo antes de entregar se reintenta; uno después, nunca | El envío paso a paso clasifica dónde falló contra un servidor SMTP falso que falla en cada punto (`test_smtp.py`) |
| El planificador solo busca; cada taller, en su transacción | Un taller que falla no para a los demás, y al cierre se comprobó que cada pasada con un taller fijado no toca los avisos de otro, aunque compartan clave |
| Ningún dato personal en la bandeja (RNF-40) | Al cierre, un barrido busca el email, el nombre, el asunto y el texto del servidor en la tabla y en la ruta de avisos; anonimizar a un cliente con avisos enviados y rechazados no deja nada suyo |

## Lo que se descubrió

| Descubrimiento | Por qué importa | Dónde ha quedado |
|---|---|---|
| **Coolify convierte `entrypoint: []` en un mapa vacío** | Falló el primer despliegue del worker, aunque local y la CI daban el fichero por bueno | El worker lleva su comando entero en `entrypoint`; trampa en CLAUDE.md y en la guía de despliegue |
| **La clave del trabajo en SAQ tenía que ser por reclamo, no por intento** | Deshacer un reclamo que no se pudo encolar devuelve el intento, y con la clave repetida SAQ descartaba el trabajo nuevo durante 10 minutos | La clave lleva la hora del reclamo. Lo encontró la prueba que comprueba el intento, escrita al romper esa guarda |
| **Leer la hora después de marcar un aviso `sent`** provocaba un *autoflush* que el CHECK rechazaba | Un 500 justo al terminar un envío que sí salió | La hora se lee antes de tocar el aviso, como al enviar un presupuesto |
| **Comprobar solo el estado no basta para el aviso de "listo"** | Deshacer y volver a marcarla lista dejaba salir el aviso del primer cambio, ya reclamado | La clave lleva el `seq` del cambio, y el compositor comprueba que sigue lista por ese mismo cambio |
| **Un enlace mágico no sirve como botón de un aviso** | Caduca en 15 minutos y un aviso se lee días después | El botón lleva a la entrada del portal con la orden ([decisión 0008](../decisiones/0008-el-boton-de-un-aviso-no-es-un-enlace-magico.md)); el portal la recuerda hasta que se entra |
| **El *fallback* del portal en Vite miraba toda la URL** | Un `?order=` con puntos cargaba la aplicación del taller | Mira solo la ruta (en Nginx nunca pasó) |
| **Los botones de anular y renovar desaparecían en cuanto el worker marcaba un presupuesto `expired`** | La interfaz preguntaba por `sent` | `awaitsAnswer` vale para las dos (paso 2, visto en el navegador) |
| **Anular mientras salía el aviso de envío no avisaba de la anulación**: el compositor de la anulación leía el de envío `claimed`, lo daba por no recibido, y el de envío salía después. Lo encontró qa-verifier | El cliente recibía "tienes un presupuesto" y nunca "se ha anulado" (especificación §6) | `status_of_key` bloquea la fila y espera a que el envío en vuelo guarde cómo acabó |
| **SAQ registra un trabajo que falla con todos sus argumentos**, y el del enlace del portal lleva el email. Lo encontró qa-verifier | El email acababa en los registros del worker (RNF-40) | Un filtro en el registro de SAQ (`app/worker.py`) escribe los trabajos sin sus argumentos; la bandeja y el enlace registran el código del servidor, nunca su texto |
| **Con el estado igual, un aviso terminado se podía reescribir**: la hora de envío, el motivo, el código. Lo encontró qa-verifier | Es el historial que ve el taller (RF-69) | `0023noticefinal`: de un aviso terminado solo cambia `updated_at`, con cualquier rol |
| **Un error sin clasificar al enviar el enlace se reintentaba** con otro enlace. Lo vio qa-verifier | Podían llegar dos correos | Se trata como en la bandeja: puede que saliera, no se reintenta |
| **Con `psql` como dueño, las tablas de un taller salen vacías** (RLS forzada) | Pareció que se habían borrado los datos de desarrollo, y se recargó la demo sin necesidad | Trampa en CLAUDE.md: para mirar, `axtton_platform` |
| **Dos pruebas pasaban sin probar lo que decían**: una de reabrir un aviso la paraba el CHECK y no el trigger, y otra miraba `__cause__` pero no el contexto encadenado. Las vio qa-verifier | Habrían seguido en verde sin su guarda | Corregidas: la primera solo choca con el trigger, la segunda mira también `__suppress_context__` |

## Qué cambió respecto al diseño

- **El botón de un aviso no es un enlace mágico**, sino la entrada del portal con la orden ([decisión 0008](../decisiones/0008-el-boton-de-un-aviso-no-es-un-enlace-magico.md)). Precisa RF-40 y la arquitectura §8.
- **Solo el enlace del portal pasa por la cola** de los emails de acceso. Las invitaciones (su token nace al invitar, en su transacción) y la recuperación de contraseña (el token lo genera SuperTokens, y encolarlo lo dejaría en Valkey) siguen saliendo de la API después del commit.
- **El aviso de anulación solo sale si el de envío salió o pudo salir**, y no lleva el motivo (que es interno).
- **El aviso de vehículo listo se cancela al deshacer el cambio** si aún no ha salido; volver a marcarla lista avisa otra vez.
- **Un aviso terminado no cambia nada**, no solo su estado (`0023noticefinal`).
- **La interfaz avisa antes de actuar** si el cliente no tiene email (RF-63), además de dejarlo en la orden.

## Lo que queda abierto

| Tema | Estado |
|---|---|
| El aviso de otros cambios de estado, si el taller lo decide (RF-61) | Sin construir; acordado dejarlo para después de F5 |
| Recordatorios de citas, vencimientos y borrado de firmas, con B7–B12 | F8 |
| Las invitaciones y la recuperación de contraseña por la cola | Siguen en la API, con su motivo (arriba). Reemitir el token de una invitación en el worker sería otro diseño |
| **Un error de la base de datos puede llevar el email en su texto** (SQLAlchemy incluye los parámetros) | El filtro quita los argumentos del trabajo, pero no el texto de un error inesperado al buscar al cliente. Se podría crear el motor con `hide_parameters` |
| **Si SAQ corta el trabajo del enlace por tiempo** a mitad de la conversación SMTP, lo reintenta con otro enlace | Raro (60 s de margen y 20 s por operación SMTP); como mucho llegan dos enlaces válidos |
| **El límite de peticiones guarda el email en una clave de Valkey** hasta una hora | Igual que al cierre de F4 |
| Probado con un servidor SMTP real de producción | No: la demo desplegada no tiene correo. Se ha probado con Mailpit y con el servidor falso |
| Migraciones arriba y abajo con datos (RNF-35) | Sin probar todavía, como al cierre de F4 |

## Riesgos que F5 ha reducido y los que siguen abiertos

- **Reducidos:** el riesgo grande que dejó F4, que un aviso saliera dos veces o ninguna, está cubierto por guardas independientes, cada una con su prueba rota a propósito, y por la clasificación de fallos del envío. Un fallo del correo ya no puede deshacer ni bloquear el cambio que lo provoca, y el taller ve qué salió y qué no.
- **Siguen abiertos:** la **entregabilidad** (que los correos de la plataforma no acaben en spam: SPF, DKIM y DMARC, en el manual de despliegue de F9) y el **paso a un servidor SMTP real**, que no se ha probado fuera de Mailpit.
