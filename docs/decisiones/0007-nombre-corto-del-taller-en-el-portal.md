# 0007 — El nombre corto del taller en la dirección del portal

- **Fecha:** 2026-11-10
- **Estado:** aceptada. Amplía la [0006](0006-enlaces-magicos-propios-ligados-al-taller.md) (añade una vía que cruza talleres) y una consecuencia de la [0005](0005-logotipo-del-taller-como-unica-imagen-subida.md) (el logotipo sale también en la entrada del portal)

## Contexto

Desde la decisión 0006, se entra en el portal desde la página de cada taller, `/portal/login/{id}`. El id es un UUID: correcto, pero imposible de imprimir en un resguardo o de dictar por teléfono. La 0006 dejó para el paso 7 de F4 un nombre corto y legible, elegido por el administrador, con estos requisitos: único en toda la instalación sin distinguir mayúsculas, con el formato de una dirección y distinto de las rutas del propio portal.

El problema está en la búsqueda. `/portal/talleres-martinez` no dice de qué taller es hasta que se busca, y no se puede fijar ningún taller para RLS antes de saberlo. Encontrar un taller por su nombre corto es, por fuerza, una consulta que mira todos los talleres. La 0006 se había cuidado de que ninguna consulta del portal lo hiciera.

## Decisión

**El nombre corto se resuelve por la vía de plataforma, con una excepción con nombre de R8.**

- **La columna** `workshops.portal_slug` (migración `0019portalslug`): de 3 a 40 caracteres, minúsculas sin tildes, dígitos y guiones, sin guion al principio ni al final ni dos seguidos (CHECK). Como se guarda siempre en minúsculas, un índice único normal basta para "sin distinguir mayúsculas". Las palabras reservadas (las rutas del portal y las que puedan llegar) están en `domain/portal.py::RESERVED_SLUGS`, porque cambian con el portal.
- **Lo elige el administrador del taller** en `/settings`, como un ajuste más (`UPDATE` de esa columna para `axtton_app`, auditado). No se puede comprobar antes si otro taller lo usa sin mirar los demás talleres: lo dice el índice único, y `flush_or_conflict` lo traduce a un 409 `portal_slug_taken`, también si dos talleres lo eligen a la vez. Cambiarlo deja de valer el anterior; vaciarlo lo quita.
- **Buscarlo** es `app/platform/portal_entry.py::workshop_id_by_slug`: con `axtton_platform`, solo el id de un taller **activo** con ese nombre **exacto**. Ni el nombre del taller, ni una lista, ni lo que se parezca. La importa `api/v1/portal/auth.py`, y `R8_EXCEPTIONS` la nombra. El nombre del taller lo da después la entrada de siempre, ya con el taller fijado.
- **Las páginas sin sesión llevan un límite por IP**: el nombre de un taller, buscarlo por su nombre corto y su logotipo cuentan juntas, 60 por minuto. Frena a quien prueba nombres para ver cuáles existen.
- **La dirección con el id sigue valiendo siempre**, también si el nombre cambia o se quita. Es la que guarda el navegador para volver a la entrada y la que llevan los enlaces de los correos.
- **El logotipo sale en la entrada**: `GET /portal/workshops/{id}/logo` sirve el PNG que el servidor volvió a dibujar al subirlo (0005), público como el nombre del taller.

## Alternativas descartadas

- **Una función de Postgres con `SECURITY DEFINER`** que devolviera el id: no toca R8, pero es una excepción al invariante 1 escondida en la base de datos, que no se ve al leer los imports del código y que ninguna prueba de arquitectura vigila.
- **Una tabla de nombres con lectura pública por RLS**: lo mismo, con una política que deja leer filas de cualquier taller a la aplicación.
- **El nombre y el id juntos en la dirección** (`/portal/talleres-martinez-4f2a…`): no cruza talleres, pero vuelve a ser una dirección que no se puede dictar.
- **Que lo elija el superadministrador**: evitaría que un taller lo cambie y deje sin valor lo que ya imprimió, pero la 0006 lo dejó al administrador y es un dato del taller como su nombre comercial.
- **Sin nombre corto**: nada cruzaría talleres, a cambio de una dirección ilegible.

## Consecuencias

- **El portal tiene una consulta que cruza talleres**, con nombre y probada: `R8_EXCEPTIONS` tiene dos entradas, y las vías de plataforma (arquitectura §4) son cinco. Lo que devuelve es un id para un nombre que el taller hace público; no permite enumerar talleres más allá de probar nombres, que el límite frena.
- **`/portal/{nombre}` comparte la raíz con las páginas del portal.** Una página nueva de una sola parte (`/portal/citas`) tiene que estar en `RESERVED_SLUGS`, o un taller podría taparla con su nombre.
- **Un taller que cambia el nombre rompe lo que imprimió con el anterior.** La pantalla lo avisa, y la dirección con el id sirve de respaldo.
- **El logotipo deja de ser solo de los documentos**: la 0005 decía que el portal no lo enseñaba. Sigue siendo la única imagen subida, y lo que se sirve es lo que dibujó el servidor.
