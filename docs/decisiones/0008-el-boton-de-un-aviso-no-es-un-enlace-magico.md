# 0008 — El botón de un aviso no es un enlace mágico

- **Fecha:** 2026-11-14
- **Estado:** aceptada. Precisa RF-40 y la arquitectura §8, que decían que los correos del taller llevan "su propio enlace de acceso"

## Contexto

La especificación (RF-40) y la arquitectura (§8) decían que los avisos al cliente (presupuesto enviado, vehículo listo) llevarían su propio enlace de acceso al portal: un clic y dentro. Al construirlos en F5 paso 5 chocaron dos cosas. Un enlace mágico caduca a los 15 minutos y sirve una sola vez (decisión [0006](0006-enlaces-magicos-propios-ligados-al-taller.md)), y un aviso se lee cuando el cliente puede, a menudo horas o días después. Y el aviso lo envía el worker sin el token (arquitectura §8): emitirlo al enviar dejaría un enlace válido durante 15 minutos en un buzón que nadie mira todavía.

## Decisión

**El botón del aviso lleva a la entrada del portal del taller con la orden**, `/portal/{nombre}?order=<id>` o `/portal/login/{taller}?order=<id>` (`domain/portal.py::order_link`). Si el cliente ya tiene sesión en ese taller, el portal abre la orden; si no, recuerda la orden, le pide el email como siempre y la abre al entrar (`portal/lib/nextOrder.ts`). El portal solo acepta ahí un UUID y solo construye con él una ruta interna.

## Alternativas descartadas

- **Un enlace mágico de larga duración solo para los avisos**: un correo reenviado o un buzón compartido daría acceso durante días. Rompe la regla de la 0006 (corta duración, un solo uso) justo en el correo que más circula.
- **Un enlace mágico de 15 minutos en el aviso**: casi siempre habría caducado al abrirlo, y el cliente vería un error en vez de su orden.
- **El enlace directo a la orden, sin entrada**: sin sesión, el cliente acabaría igualmente en la entrada, pero sin saber de qué taller ni qué orden buscaba.

## Consecuencias

- **El cliente sin sesión pide el enlace una vez más** (un paso más que con un enlace directo), y a cambio el correo no da acceso a nadie que lo vea.
- **La entrada del portal acepta `?order=`**, que se guarda en el navegador solo para ese taller y se usa una vez (`takeNextPath`).
- **El fallback del portal en Vite tuvo que mirar solo la ruta**: un `?order=` con puntos cargaba la aplicación del taller (en Nginx nunca pasó).
