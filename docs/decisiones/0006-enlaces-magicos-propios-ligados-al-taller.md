# 0006 — Enlaces mágicos propios, pedidos desde la entrada de cada taller

- **Fecha:** 2026-11-04
- **Estado:** aceptada. Cambia RF-45 y la resolución de R3 de la especificación (2026-10-22)

## Contexto

El cliente entra en el portal con un enlace mágico (RF-40), y cada sesión solo ve un taller. La arquitectura (A4, §7.2) preveía la receta `passwordless` de SuperTokens. La especificación (RF-45, R3) decía que un email cliente de varios talleres recibiera **un único email con un enlace por taller**: el cliente escribía solo su email, y el sistema lo buscaba en todos los talleres. Era el riesgo principal de la arquitectura (§12), así que F4 empezó con una prueba corta de la receta, con el SDK 0.31.3 y el core 12.2.0:

- `create_code(email)` dos veces para el mismo email crea dos dispositivos, cada uno con su código.
- **Consumir uno de los dos borra todos los dispositivos de ese email.** El segundo código responde `RESTART_FLOW_ERROR`: ya no existe.
- `signinup(email)`, llamado desde el servidor, devuelve el mismo usuario de la receta para el mismo email, siempre, sin enviar ningún código.

Con los códigos de SuperTokens, abrir el enlace del taller A dejaba inservible el del taller B. Se construyó entonces un enlace propio con un botón por taller en el mismo email. Al revisarlo aparecieron dos problemas más de esa forma de entrar:

- **Un email que es cliente de muchos talleres** recibiría un correo con un botón por cada uno: con 1000, un correo inutilizable. Haría falta un tope arbitrario.
- **La búsqueda del email en todos los talleres** era la segunda vía de plataforma que importaba un endpoint del portal (R8), y la única consulta del portal que cruzaba talleres.

## Decisión

**Se entra en el portal desde la dirección de cada taller, y el enlace es nuestro.**

- **La página de entrada es de un taller**: `/portal/login/{taller}`. El taller la da en su web, en el resguardo o en sus correos, y la página enseña su nombre (y, desde el paso 7 de F4, su logotipo). `/portal/login` sin taller no pide nada: explica que se entra desde la dirección del taller o desde sus correos. Por ahora el taller va por su id. Un nombre corto y legible lo elegirá el administrador en el paso 7 (ver abajo).
- **Pedir el enlace** (`POST /api/v1/portal/auth/request-link`, con el taller y el email) fija ese taller y busca al cliente por su email **bajo RLS**, como cualquier petición. Si existe y está activo, se le envía **un** enlace. La respuesta es siempre un 202 vacío, se haga o no, y todo ocurre después de responder (RF-41).
- **El token lo genera el backend** (`core/tokens.py`, como las invitaciones) y se guarda **solo su hash** en `portal_links` (migración `0016portallinks`), una tabla del taller con RLS forzada, con su cliente, su caducidad (15 minutos) y cómo se cerró (`used_at` o `revoked_at`).
- **Consumir** (`POST /api/v1/portal/auth/consume`) fija el taller que dice la URL y cierra el enlace con una sola sentencia que comprueba y escribe a la vez. Un enlace de otro taller no se ve (RLS, T5), y uno usado o caducado no se actualiza (T6). Después, `signinup(email)` da el usuario de la receta, y `core/sessions.py` crea la sesión con `actor: client`, el taller y el cliente **del enlace guardado** (T10).
- **Las rutas de la receta en SuperTokens no existen**: crear, reenviar y consumir códigos, y "¿existe este email?". Su servicio de correo falla si algo intentara usarlo.
- **El token viaja en el fragmento** (`/portal/access/{taller}#{token}`): el navegador no lo envía al servidor, así que no queda en los registros del proxy ni en la cabecera Referer. La página no entra sola al abrirse: pide pulsar un botón, porque algunos correos abren los enlaces para revisarlos y gastarían uno que solo sirve una vez.
- **No se guarda el email en el enlace.** Al consumirlo se lee el del cliente. Cambiar el email o anonimizar al cliente revoca sus enlaces pendientes en la misma transacción. Emitir bloquea al cliente (`FOR SHARE`), y así un cambio de email a la vez también ve el enlace recién emitido.

**El nombre corto del taller en la dirección** (paso 7 de F4) tendrá que ser:
- **único en toda la instalación**, sin distinguir mayúsculas;
- una dirección válida: minúsculas sin tildes, dígitos y guiones, sin guion al principio ni al final ni dos seguidos, y de 3 a 40 caracteres;
- distinto de las rutas del propio portal (`login`, `access`…).

La dirección con el id del taller seguirá valiendo, también si el nombre cambia.

## Alternativas descartadas

- **Los códigos de la receta, uno por taller:** consumir uno borra los demás del email (arriba).
- **El cliente solo escribe su email y recibe un correo con un enlace por taller** (lo que decía RF-45): con muchos talleres, un correo inutilizable que obligaría a un tope arbitrario; además, una búsqueda entre talleres con la vía de plataforma desde el portal. Fue lo primero que se construyó, y se retiró antes de fusionarlo.
- **Un solo enlace por email y un selector de talleres dentro del portal**, como el del personal (A6): sería cómodo para quien va a varios talleres, y anonimizar o cambiar el email cortaría el acceso en cada petición sin revocar sesiones. Pero haría del portal un portal de la plataforma, por encima de los talleres, y una sesión robada daría acceso a todos los del email.
- **Elegir el taller en un desplegable al pedir el enlace:** la lista de talleres de la instalación sería pública, sin sesión. Y un taller mal elegido no se puede avisar sin romper RF-41: el cliente no recibiría nada sin saber por qué.
- **Un *tenant* de SuperTokens por taller:** la multitenencia es de pago, obliga a dar de alta un *tenant* con cada taller y mezcla el aislamiento entre talleres, que es de RLS, con la configuración de un tercero.
- **Guardar el email en el enlace (o su hash) y compararlo al consumir:** guarda un dato personal más, que la anonimización (RNF-40) tendría que borrar de una tabla sin `DELETE`.

## Consecuencias

- **Ninguna consulta del portal cruza talleres.** Las vías de plataforma (arquitectura §4) son cuatro, y `R8_EXCEPTIONS` solo contiene el selector de talleres del personal.
- **Quien es cliente de varios talleres entra en cada uno desde su dirección**, y cada enlace abre una sesión que solo ve ese taller. En un mismo navegador, entrar en otro taller sustituye la sesión del anterior.
- **El portal es de cada taller**, y su entrada se puede personalizar con la configuración del taller.
- **Un solo usuario de SuperTokens por email de cliente**, como ya decía §2: revocar sus sesiones nunca puede ser `revokeAllSessionsForUser` (paso 2 de F4).
- **La caducidad y el "un solo uso" son nuestros**, y se prueban como el resto: `test_portal_auth.py`, con dos transacciones reales para el doble uso y para el cambio de email mientras se emite. Un trigger (`portal_links_closed_frozen`) impide, con cualquier rol, reabrir un enlace cerrado.
- **Las filas de `portal_links` se acumulan.** Son pequeñas y sin datos personales; borrar las viejas será una tarea programada del worker (F5).
- **Sin SMTP no se emite ningún enlace**: no llegaría a nadie. La demo de producción no tiene correo; cómo entra en ella un cliente se decide en el paso de la demo.
