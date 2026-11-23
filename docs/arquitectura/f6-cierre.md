# Cierre de F6: lo aprendido

> Fase cerrada el 2026-11-23. Commits `ede845a` a `3eff600`, más el arreglo `cc648a3` y el PR del cierre. Cada paso llegó a producción al fusionarse, salvo el paso 3: la CI de `main` falló esa noche por una prueba de la demo (abajo) y llegó con el arreglo.

F6 era **los documentos generados** (especificación §7): la hoja de recepción firmada, el resumen de entrega y el informe de actuaciones, y su descarga en el portal. Lo difícil no era maquetar PDF, que ya se hacía desde F3, sino el invariante 6 en una pieza nueva: una hoja firmada **no cambia nunca, con ningún rol**, salvo vaciar lo personal al anonimizar, y la firma tiene que llegar del navegador sin convertirse en una puerta para inyectar contenido.

Lo construido, en ocho pasos (eran nueve; la prueba de punta a punta salió de la fase, [decisión 0009](../decisiones/0009-punta-a-punta-como-fase-opcional.md)):

1. Los datos de recepción que pide RF-51 en la orden (combustible, daños, objetos, renuncia) y `reception_sheets`, la hoja firmada, que nace al firmar con su copia congelada y un trigger que la congela con cualquier rol (`0024receptionsheets`).
2. Firmar en pantalla, con los trazos como números, o marcarla firmada en papel; la corrección posterior en la auditoría, y la renuncia firmada para "sin presupuesto" (RF-52, RF-27).
3. El PDF de la hoja: sin firmar, desde la orden; firmada, desde su copia, idéntico byte a byte (RF-55).
4. Los km al entregar (`0025deliverykm`) y el resumen de entrega con la garantía de 3 meses o 2.000 km (RF-53).
5. El informe de actuaciones del vehículo, con los titulares y los importes solo para el administrador y auditados (RF-18, RNF-52).
6. En el portal, la hoja firmada, el resumen de entrega y hasta cuándo dura la garantía (RF-54).
7. La demo: hojas firmadas en pantalla y en papel, los km de cada entrega y un vehículo con órdenes de dos titulares.
8. El cierre: qa-verifier y docs-writer contra todo lo anterior, con lo que encontraron ya corregido (`0026frozenjson`, abajo).

Al terminar, **1.573 pruebas** contra Postgres, SuperTokens y Valkey reales.

## Lo que se confirmó

| Idea del diseño | Cómo se comprobó |
|---|---|
| Una fila es una hoja ya firmada; sin firmar, la hoja sale de la orden | La sin firmar y la firmada salen de la misma función (`snapshot_of`): lo que se ve antes de firmar es lo que queda firmado. Corregir la recepción después no cambia el PDF firmado, byte a byte |
| La hoja firmada no cambia con ningún rol (invariante 6) | El trigger, con los tres roles: once columnas distintas, el vaciado a medias, otro nombre en lugar del borrado, una clienta anonimizada que no es la de la hoja, `TRUNCATE`. Al cierre se rompió de cuatro maneras y cada una hizo fallar pruebas |
| La firma viaja como números, nunca como imagen (§7.3) | Al cierre, 28 cuerpos hostiles y una prueba por propiedades (Hypothesis): o se rechaza, o sale un SVG de solo números dentro del lienzo |
| Dos firmas a la vez, o firmar mientras se corrige, cancela o entrega, van una detrás de otra | Con transacciones reales: el bloqueo de la orden, la versión y el índice único se cubren entre sí. Sin el bloqueo, la versión sigue parando la carrera; sin los dos, las hojas acababan en órdenes canceladas |
| Lo personal de la hoja se vacía al anonimizar (RNF-40) | El barrido de todas las tablas, con una hoja firmada en pantalla y otra en papel por la API, y el PDF de después con "Cliente eliminado" |
| El portal solo da lo del cliente (T4, RF-44) | El barrido T4 de F4 recorre solo las rutas nuevas desde el OpenAPI; quien compra el coche no ve la hoja ni el resumen del dueño anterior |
| El informe no lleva nombres ni importes si no se piden | Al cierre, con cobros, decisiones con nota y una titular anonimizada, en las tres variantes |
| Cien órdenes en menos de 10 s (RNF-52) | Una consulta por tipo de dato, nunca una por orden: unos 4,5 s en local, medido en cada CI |

## Lo que se descubrió

| Descubrimiento | Por qué importa | Dónde ha quedado |
|---|---|---|
| **`None` en una columna JSONB se guarda como el JSON `null`**, no como SQL NULL | El CHECK con `signature IS NULL` rechazaba la firma en papel | `JSONB(none_as_null=True)` en `reception_sheets.signature`; trampa en CLAUDE.md |
| **WeasyPrint dibuja un SVG como trazos de la página**, no como una imagen | La prueba que buscaba la firma como imagen no la encontraba | `test_reception_pdf.py` cuenta los segmentos de la página |
| **Los km al entregar provocaban un *autoflush*** antes del cambio de estado, y el CHECK de los km los rechazaba | Un 500 al entregar | Se escriben después del cambio de estado, como al enviar un presupuesto |
| **Firmar tenía que subir la versión de la orden** | Una corrección abierta antes de firmar se guardaba después sin dejar constancia | `sign` toca `updated_at`: quien corregía recibe un 409 y ve la hoja firmada |
| **La demo fechaba en UTC**: entre las 00:00 y las 02:00 de Madrid, una entrega de hace 19 días salía de hace 20 | Falló la CI de `main` al fusionar el paso 3 y no se desplegó | `cc648a3`: la demo cuenta en el calendario del taller |
| **La demo renumera las órdenes después de firmar**, y la copia congelada guardaba el número viejo | El PDF de la hoja firmada decía OT-2026-0001 en la orden 0002 | `_backdate_sheets` corrige la hora y el número de la copia, con el trigger desactivado solo en esa transacción |
| **En `jsonb`, `1` es igual a `1.0`.** Lo encontró qa-verifier | Los triggers de la hoja firmada y del presupuesto enviado dejaban reescribir los números de lo congelado: el PDF decía "123.456.0 km" y dejaba de ser idéntico (RF-55) | `0026frozenjson`: lo congelado se compara como texto, que guarda la escala de cada número |
| **Un `NaN` o un `Infinity` en cualquier cuerpo daba un 500**, no un 422. Lo encontró qa-verifier | El manejador de FastAPI devolvía la entrada (`input: nan`) y la respuesta no se podía escribir en JSON | Un manejador propio de `RequestValidationError` en `main.py`, que tampoco devuelve lo que se mandó |
| **Firmar en papel guardaba el nombre de quien firmó**, que el PDF nunca enseña. Lo vio qa-verifier | Un dato personal guardado para nada | La API lo rechaza (`signer_name_not_expected`) |
| **Una prueba de F4 escribía `d` donde quería `\d`** en una expresión regular. La vio qa-verifier | Podía fallar por azar con una marca de tiempo | Corregida |

## Qué cambió respecto al diseño

- **Sin firmar no hay fila**: la hoja nace al firmar, no al abrir la orden, y hasta entonces sale de la orden. La matriz de documentos de la especificación (§7) lo dice ya.
- **La firma viaja como trazos y el servidor escribe el SVG** (arquitectura §7.3), en vez de recibir una imagen.
- **El mecánico genera el informe de actuaciones básico**: la especificación se contradecía (§3 contra §4) y se decidió a favor de §4, con los titulares y los importes solo para el administrador.
- **En el portal, solo la hoja firmada** (decidido por el usuario): la sin firmar es para el mostrador.
- **La firma de un cliente anonimizado se sigue viendo** en el PDF del taller hasta su plazo (decidido por el usuario al cerrar la fase): "bloqueada" en RF-56 quiere decir que no se borra ni se cambia, no que deje de servir de prueba.
- **La prueba de punta a punta pasó a una fase opcional** al final del proyecto ([decisión 0009](../decisiones/0009-punta-a-punta-como-fase-opcional.md)).

## Lo que queda abierto

| Tema | Estado |
|---|---|
| El plazo de la firma, su borrado y el aviso previo al taller (RF-56, RF-57) | F8. En F6 solo existe la columna `signature_purged_at` y el trigger que no deja firmar con la firma ya borrada |
| La garantía mayor de una pieza y las piezas que de verdad se montaron | F7: hasta entonces, las piezas son las líneas del último presupuesto aprobado |
| La prueba de punta a punta con Playwright | Fase opcional al final ([decisión 0009](../decisiones/0009-punta-a-punta-como-fase-opcional.md)); hasta entonces, a mano y por qa-verifier |
| Migraciones arriba y abajo con datos (RNF-35) | Sin probar todavía, como en F4 y F5. `0026frozenjson` se aplicó, se deshizo y se volvió a aplicar en la base de desarrollo |

## Riesgos que F6 ha reducido y los que siguen abiertos

- **Reducidos:** el riesgo de §12 de la arquitectura (una firma recibida como SVG sería una puerta para inyectar contenido) queda cerrado: la firma son números y el servidor dibuja. Lo congelado ya no admite cambios que Postgres daba por iguales.
- **Siguen abiertos:** el borrado de las firmas a su plazo (F8), sin el cual una firma se guarda indefinidamente; y que la interfaz, sin prueba de punta a punta, se puede romper sin que la CI lo vea.
