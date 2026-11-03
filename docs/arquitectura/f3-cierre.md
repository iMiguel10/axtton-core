# Cierre de F3: lo aprendido

> Fase cerrada el 2026-11-03. Commits `d89f59b` a `cc84885`, más el PR del cierre. Como en F2, cada paso llegó a producción al fusionarse: la demo está en <https://axtton.imigueldev.duckdns.org>.

F3 era **el presupuesto** (especificación §9): lo que el taller propone, lo que el cliente acepta y lo que no puede cambiar después. Que un presupuesto enviado no se toque, ni por un fallo de la aplicación ni por SQL, y que sus importes cuadren siempre igual en la pantalla, en el PDF y, en F4, en el portal.

Lo construido, en nueve pasos:

1. Los datos legales del taller, sus ajustes y las tarifas de mano de obra, editables por su administrador, y el logotipo como única imagen que se sube ([decisión 0005](../decisiones/0005-logotipo-del-taller-como-unica-imagen-subida.md); RF-02, migración `0012settings`).
2. La regla única de los totales (descuento por línea, descuento global repartido, IVA por línea y desglose), con pruebas por propiedades, y la validez en días hábiles (RF-33; `domain/quotes.py`, `domain/business_days.py`).
3. Las tablas de presupuesto con sus triggers: una fila por versión, y lo enviado congelado con cualquier rol (invariante 6, migración `0013quotes`).
4. El borrador: uno por orden, guardado entero con bloqueo optimista, y el listado de presupuestos.
5. Enviar, corregir, renovar y anular, con la orden en `pending_approval` y de vuelta a su origen.
6. La decisión registrada por el taller (teléfono o en persona) y el importe a cobrar de la última versión aprobada (RF-29).
7. El PDF de cada versión enviada, idéntico byte a byte cada vez, con el vehículo y el plazo de entrega congelados al enviar, y la vista previa del borrador con marca de agua (RF-37, RF-55, migración `0014quotepdf`).
8. Los filtros del listado de órdenes por estado, responsable y fecha prevista, pendientes de F2 (RF-24).
9. Los presupuestos en la demo y el cierre.

Y el cierre: qa-verifier y docs-writer contra todo lo anterior, con lo que encontraron ya corregido (ver abajo). Al terminar, **847 pruebas** contra Postgres, SuperTokens y Valkey reales.

## Lo que se confirmó

| Idea del diseño | Cómo se comprobó |
|---|---|
| Lo enviado no cambia con ningún rol (invariante 6) | Los triggers `quote_lines_frozen` y `quotes_frozen_after_send` rechazan el cambio también al dueño de las tablas, incluida la exigencia de que las líneas sumen el total guardado. Al cierre, `test_adverse_f3.py` lo prueba con los tres roles, y lo mismo con las decisiones (ver abajo) |
| Los totales salen de una sola regla | `domain/quotes.py` es la única que calcula; el navegador enseña lo que devuelve la API. Las pruebas por propiedades comprueban que el desglose cuadra y que el descuento global nunca deja una base negativa |
| El PDF de una versión enviada sale siempre igual (RF-55) | WeasyPrint es determinista si no se le da la fecha de generación: la prueba compara dos PDF byte a byte. Lo que cambia después (los datos del taller, el logotipo, el nombre del cliente) se lee en vivo; el vehículo y los km, que forman parte de lo presupuestado, se congelan |
| Los bloqueos en cadena evitan los 500 | Orden y luego versión, siempre en ese orden. Cada carrera tiene su prueba con dos transacciones reales (`test_quote_send.py`, `test_quote_decision.py`, `test_adverse_f3.py`), y qa-verifier rompió seis guardas a propósito para verlas fallar |
| El mecánico no ve importes si el taller lo desactiva | `test_adverse_f3.py` recorre la ficha, el listado, el PDF y la vista previa con un mecánico |
| RLS aísla las tablas nuevas | `test_rls_tables.py` las incluye, y los triggers BEFORE paran la fila de otro taller antes que WITH CHECK, con otro mensaje pero el mismo aislamiento |
| Anonimizar no deja rastro (RNF-40) | Al cierre, `test_adverse_f3.py` pasa el barrido de `test_anonymize.py` sobre un cliente con presupuestos enviados y decididos, y su PDF dice "Cliente eliminado" |
| La demo cumple las reglas | Sus presupuestos pasan por los services y luego se mueven las fechas; `test_seed_demo.py` comprueba que hay uno en cada estado y uno caducado |

## Lo que se descubrió

| Descubrimiento | Por qué importa | Dónde ha quedado |
|---|---|---|
| **El orden de las escrituras al enviar lo imponen los triggers**: las líneas con sus importes, en su propio `flush`, antes de marcar la versión como enviada; la anterior, sustituida antes de enviar la nueva | En un solo `flush`, el ORM escribe primero la versión y las líneas llegarían a una ya enviada; y el índice único parcial de `sent` no es diferible | `send_quote` y su docstring; CLAUDE.md |
| **Una consulta a mitad del envío provoca un *autoflush*** de la versión marcada "enviada" sin sus totales | El CHECK `ck_quotes_sent_fields` la rechazaba con un 500 | Todo lo que se lee va antes de tocar la versión; CLAUDE.md |
| **Repartir el descuento global dándolo todo a la línea mayor** podía dejar una base negativa | Una línea con base negativa no es un presupuesto válido | Reparto proporcional a cada base, con los céntimos sobrantes uno a uno a las de mayor parte decimal, así que ninguna recibe más que su base (`domain/quotes.py`); pruebas por propiedades |
| **Renovar no es cambiar `valid_until`**: el trigger lo prohíbe, y con razón | El PDF de lo que se envió tiene que seguir saliendo igual | Renovar envía una copia con validez nueva y deja la renovada como sustituida |
| **El plazo de entrega es obligatorio** (RD 1457/1986, art. 14) y se cuenta desde la aceptación, no desde el envío | Una fecha fija al enviar sería falsa si el cliente tarda en decidir | `delivery_business_days` en el borrador, el valor por defecto del taller y sin él no se envía |
| **Lo que se esperó a bloquear puede no existir ya**: un descarte delante de un envío, un guardado u otro descarte dejaba al segundo sin fila tras el `FOR UPDATE`, y un `assert` lo convertía en un 500. Lo encontró qa-verifier | Basta un doble clic en "Descartar" o dos pestañas | Un 404 `quote_not_found`; CLAUDE.md |
| **Las decisiones solo las protegían los permisos**: el dueño de las tablas podía cambiar el resultado, la fecha o borrarlas. Lo encontró qa-verifier | El invariante 6 dice "jamás", y las versiones ya estaban protegidas con un trigger para cualquier rol | Migración `0015decisionsfrozen`, con el trigger `quote_decisions_frozen` |
| **Anular una versión ya marcada `expired` dejaba la orden en `pending_approval`** sin nada que esperar. Latente hasta que el worker la marque (F5). Lo encontró qa-verifier | Sería una orden atascada en cuanto exista el worker | `cancel_quote` trata igual una enviada y una caducada: las dos son la que espera respuesta |
| **El fetcher de WeasyPrint sirve recursos por nombre** (`axtton:logo`), sin `data:` ni nada externo | Una plantilla no puede hacer que el servidor cargue una URL | `infra/pdf.py`; decisión 0005 |

## Qué cambió respecto al diseño

- **El plazo de entrega** no estaba en el modelo de `quotes`: llegó con el PDF (`delivery_business_days`, y `default_delivery_business_days` en `workshops`).
- **El vehículo se congela al enviar** (`vehicle_snapshot`); los datos del taller y del cliente, no. Una corrección de la ficha del taller no obliga a reenviar lo enviado.
- **Los festivos autonómicos y locales** no cuentan todavía: solo alargarían la validez. El calendario del taller (horario, festivos propios y cierres) pasa a F8.
- **`0014quotepdf` desactiva el trigger que congela lo enviado** para rellenar las dos columnas nuevas en las versiones ya enviadas (solo existían en la demo y en desarrollo), dentro de su transacción y quitando la RLS forzada un momento. Es la única migración que lo hace. Si otra lo necesitara con datos reales, iría a la bitácora de decisiones antes de escribirla.

## Lo que queda abierto

| Tema | Estado |
|---|---|
| El aviso al cliente y la marca `expired` escrita | Con el worker, en F5. Hasta entonces la caducidad se decide por `valid_until`, y el trigger de las decisiones no deja aprobar fuera de plazo |
| La decisión desde el portal, el email de presupuesto enviado y el PDF para el cliente | F4 y F5 |
| El calendario del taller y los festivos propios en la validez (RF-33) | F8 |
| `part_id` y las líneas desde el catálogo | F7 |
| **RF-16**: proponer la siguiente revisión al entregar | Sigue pendiente de los intervalos del taller (F8) |
| Migraciones arriba y abajo con datos (RNF-35) | Sin probar todavía, como al cierre de F2 |

## Riesgos que F3 ha reducido y los que siguen abiertos

- **Reducidos:** que un presupuesto enviado o una decisión cambien (triggers con cualquier rol, probados con los tres), que los importes difieran entre pantallas (una sola regla, calculada en el servidor) y que dos personas pisen el mismo borrador (bloqueo optimista y bloqueos en cadena).
- **Sigue abierto, y es el siguiente riesgo grande:** el enlace mágico ligado a un taller con la receta `passwordless` (arquitectura §12). Se prueba al principio de F4, que además es donde el cliente decidirá por sí mismo sobre lo que F3 congela.
