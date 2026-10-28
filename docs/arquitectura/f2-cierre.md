# Cierre de F2: lo aprendido

> Fase cerrada el 2026-10-28. Commits `ce244aa` a `8a20a32`, más el PR del cierre. Desde F2 cada fase termina en producción: la demo está en <https://axtton.imigueldev.duckdns.org>.

F2 era **el núcleo operativo del taller** (especificación §9): clientes, vehículos con su titularidad y órdenes con su ciclo de vida, editables a la vez por varias personas sin pisarse y sin perder lo escrito si se va la conexión. Y descubrir pronto los problemas de desplegar.

Lo construido, en diez pasos y tres añadidos:

1. Clientes, con email único por taller, edición con bloqueo optimista y archivo (RF-10).
2. Vehículos y titularidad: periodos que no se solapan (`EXCLUDE`) y se congelan al cerrarse, y el cambio de titular auditado (RF-11 a RF-13).
3. Órdenes con numeración por taller y año del taller, e historial de estados append-only con el invariante 5 vigilado por un trigger diferido (RF-20, RF-21).
4. El ciclo de vida: transiciones con quién hace cada una, "sin presupuesto" y deshacer el último cambio (§6, RF-26, RF-27).
5. Diagnóstico versionado, notas internas y trabajos que se anulan en vez de borrarse (RF-22 a RF-26).
6. La búsqueda única del mostrador, por matrícula, nombre sin tildes y teléfono (RF-14).
7. Borradores sin conexión, que se reenvían al volver sin duplicar (RNF-22).
8. El cobro de las órdenes cerradas y la anonimización de un cliente (RF-28, RF-29, RF-15, RNF-40).
9. El rediseño de la interfaz y los correos con la marca, y (9b) los límites de recursos por taller (§10, RF-114) y (9c) el versionado ([decisión 0003](../decisiones/0003-versionado-por-etiquetas-y-release-please.md)).
10. El primer despliegue en Coolify, con la demo como primera instalación ([decisión 0004](../decisiones/0004-produccion-en-coolify.md)).

Además: los datos de demostración, que la demo desplegada recarga cada noche ([guía](../guias/demo.md)), y el paso a ramas y PR con `main` protegida.

Y el cierre: qa-verifier y docs-writer contra todo lo anterior, con lo que encontraron ya corregido. Al terminar, **576 pruebas** contra Postgres, SuperTokens y Valkey reales.

## Lo que se confirmó

| Idea del diseño | Cómo se comprobó |
|---|---|
| RLS aísla también las tablas nuevas | `test_rls_tables.py` las recorre todas (su control falla si aparece una tabla con `workshop_id` fuera de la lista), y al cierre `test_adverse_f2.py` añade, en las diez tablas de F2, que desde un taller no se puede insertar una fila del otro ni mover una propia al otro |
| El historial es la fuente del estado (invariante 5) | El `CONSTRAINT TRIGGER` diferido rechaza al confirmar cualquier transacción que deje el estado distinto del último cambio, con cualquier rol |
| El cliente de una orden es el titular al abrirla (invariante 7) | La apertura bloquea el vehículo antes de leer el titular, y al cierre la base de datos impide cambiar después el cliente o el vehículo (ver abajo) |
| Lo que cuenta se pone en fila | Cada carrera nueva tiene su prueba con dos transacciones reales, y se rompió a propósito cada guarda para verla fallar: los límites (clientes, vehículos, órdenes del mes), el cobro desde la misma versión, la nota y el trabajo enviados dos veces, anonimizar frente a abrir una orden o dar un vehículo |
| La matriz de permisos se cumple en todas las rutas | Al cierre, una prueba recorre las 41 rutas de `/workshop` del OpenAPI con un mecánico, y otra obliga a clasificar cualquier ruta nueva. Dar `RECORD_PAYMENT` al mecánico la hace fallar |
| Anonimizar no deja rastro (RNF-40) | Un barrido convierte todas las tablas en texto y busca lo que el cliente era. Una columna nueva con datos personales lo hace fallar |
| La demo cumple las reglas | Se crea con los services de verdad; una regla nueva que no cumpla hace fallar `test_seed_demo.py` |

## Lo que se descubrió

| Descubrimiento | Por qué importa | Dónde ha quedado |
|---|---|---|
| **`axtton_app` podía cambiar el cliente, el vehículo y el número de una orden abierta.** Solo se le había quitado el `DELETE` | El invariante 7 lo protegía solo el código, y en F4 el portal dará acceso por `work_orders.client_id`. Lo encontró qa-verifier | Migración `0011ordercols`: `UPDATE` solo sobre las columnas que cambian con la vida de la orden; `test_adverse_f2.py` |
| **Una carrera no se prueba con `asyncio.gather` sobre la API**: el cliente en memoria atiende las peticiones una tras otra | La prueba del email único de clientes pasaba aunque se quitara la guarda | Dos transacciones intercaladas a mano (`test_concurrency.py`); CLAUDE.md |
| **Bajo RLS, un índice solo sirve para condiciones `LEAKPROOF`**: `LIKE` no lo es, y el índice trigram nunca se usaba | La búsqueda parecía indexada y no lo estaba | Columnas generadas y `EXPLAIN` como `axtton_app` con volumen (`test_search.py`); CLAUDE.md |
| **Quien bloquea con `FOR SHARE` y luego actualiza se interbloquea** con otro igual | Registrar dos trabajos a la vez en la misma orden acababa en un deadlock | `FOR NO KEY UPDATE` en `order_repo.get_for_activity`; CLAUDE.md |
| **Sin conexión, TanStack Query pausa las mutaciones en vez de fallar**, y un envío que "falló" puede haber llegado | El borrador no sabía que estaba pendiente; reenviarlo podía duplicar la nota | `networkMode: "always"` e ids del borrador como clave; si lo pendiente se edita, cambia de id |
| **El año de una orden es el del taller**, no el de UTC | A las 23:30 UTC del 31 de diciembre, en Madrid ya es el año siguiente | `order_repo.local_year`; las fechas de la interfaz en la zona del taller (`useDates`) |
| **Las redirecciones de la API salían con `http://`** detrás del proxy, porque uvicorn no se fía de `X-Forwarded-Proto` | Una URL con barra final llevaba al navegador fuera del HTTPS. Lo encontró qa-verifier | `proxy_redirect` en `deploy/web/nginx.conf` |
| **`/api/v1/meta` no prueba qué código se construyó**: su commit es la variable que pone la CI | Si `main` avanzaba durante el despliegue, se publicaba un commit sin probar con la versión del anterior. Lo encontró qa-verifier | `coolify-deploy.sh` compara además el commit que Coolify clonó |
| **Una variable vacía en compose llega como `""`, no como ausente** | Pisaba los valores por defecto de `Settings` (un usuario SMTP vacío) | Los valores por defecto se repiten en `compose.prod.yml`; CLAUDE.md |

## Qué cambió respecto al diseño

- **Los límites de recursos** se adelantaron a F2 (estaban como límites de cuenta sin construir): cada taller nace con los del plan básico y el superadministrador los ajusta; la demo usa unos más bajos.
- **El versionado y la protección de `main`** no estaban en el diseño: se decidieron antes del primer despliegue (decisión 0003). Los commits pasan a ser convencionales.
- **La primera instalación es la demo**, no una instalación real más la demo: no hay ningún taller que la use (decisión 0004).
- **`work_order_counters` no lleva `id`**: su clave es `(workshop_id, year)` y nadie la referencia (arquitectura §3).
- **El cambio de estado `opened`** es el primero de toda orden, para que el invariante 5 se cumpla también recién abierta.

## Lo que queda abierto

| Tema | Estado |
|---|---|
| **RF-24**: filtrar el listado de órdenes por estado, mecánico responsable y fecha prevista | La API filtra por estado y responsable, pero la interfaz no lo ofrece; por fecha prevista no filtra nada. Encontrado por docs-writer; pendiente de decidir si entra antes de F3 |
| **RF-16**: proponer la siguiente revisión al entregar una orden de mantenimiento | Necesita los intervalos del taller, que no se configuran todavía: con los datos del taller (F3) o con los vencimientos (F8) |
| `/docs` y `/openapi.json` públicos en producción | Intencionado mientras sea una demo de portfolio; a revisar con una instalación real |
| Las copias de seguridad (RNF-33) | F9. Mientras la única instalación sea la demo, que se recarga cada noche, no hay nada que perder |
| Los límites de memoria por contenedor | En reposo, la pila ocupa unos 550 MB. Se fijarán si el servidor se queda justo |
| El job `deploy` de la CI | Construido y con sus piezas probadas (la llamada a Coolify que pone las variables, `/meta`), pero su primera ejecución entera será con el siguiente PR fusionado |
| Migraciones arriba y abajo con datos (RNF-35), y un arranque con volúmenes vacíos en la CI | Sin probar todavía. El arranque desde cero sí se probó a mano con `compose.prod.yml` |
| T4–T7 y T10 (cliente) | Llegan con el portal, en F4 |

## Riesgos que F2 ha reducido y los que siguen abiertos

- **Reducidos:** la edición concurrente (bloqueo optimista, bloqueos en fila y sus pruebas), perder lo escrito sin conexión, la fuga de datos de un cliente anonimizado y desplegar: el camino de un PR a producción ya existe y comprueba lo que publica.
- **Sigue abierto, y sigue siendo el siguiente riesgo grande:** el enlace mágico ligado a un taller con la receta `passwordless` (arquitectura §12). Se prueba al principio de F4.
- **Nuevo a vigilar:** el servidor es compartido con otros servicios propios y construye las imágenes en cada despliegue. Si los despliegues se vuelven lentos o la memoria se queda justa, la alternativa descartada (construir en GitHub y publicar en un registro) vuelve a estar sobre la mesa.
