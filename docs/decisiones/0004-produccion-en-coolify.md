# 0004 — Producción en Coolify, con un Nginx propio y la demo como primera instalación

- **Fecha:** 2026-10-28
- **Estado:** aceptada

## Contexto

F2 termina con el primer despliegue (especificación §9). La arquitectura (§9) ya fijaba lo esencial: Coolify, un solo dominio, un servicio `web` que sirve las dos aplicaciones y reenvía `/api`, ningún otro servicio con dominio, despliegue continuo desde `main` y una demo que se recarga cada noche. Faltaba decidir cómo se construye cada pieza y qué instalación se despliega primero. Applications Tracker ya resolvió el mismo camino en el mismo servidor (su decisión 0023), y casi todo se hereda.

## Decisión

- **`compose.prod.yml`** con `web`, `api`, `db`, `supertokens`, `supertokens-db` y `valkey`. Ningún servicio publica puertos: el proxy de Coolify pone el HTTPS y llega a `web` por la red de Docker.
- **Un Nginx propio** (`deploy/web/`): sirve el taller en `/` y el portal en `/portal`, cada uno con su *fallback* a su `index.html`, reenvía `/api` a la API y pone una primera capa de límite por IP y las cabeceras de seguridad, con la CSP.
- **Postgres con el script de los roles dentro de la imagen** (`deploy/postgres/Dockerfile`), no montado desde el repositorio. La base de pruebas solo se crea si existe `POSTGRES_TEST_DB`, que en producción no está.
- **El despliegue lo pide la CI, no Coolify.** El job `deploy` de `ci.yml` corre tras un push a `main` con todo en verde y llama a la API de Coolify (`deploy/coolify-deploy.sh`): le pone la versión (`APP_VERSION`, `APP_COMMIT`), pide el despliegue, espera y comprueba que `/api/v1/meta` responde ese commit. El *Auto Deploy* de Coolify queda desactivado.
- **La primera instalación es la demo pública**, en `axtton.imigueldev.duckdns.org`, con `DEMO_SEED_ENABLED=true` y una tarea programada de Coolify que cada noche ejecuta `seed_demo --purge-other-accounts`. Una instalación real, cuando la haya, será otro recurso de Coolify con el mismo `compose.prod.yml`.
- **Sin correo en la demo.** La aplicación funciona sin SMTP (RNF-32).

## Alternativas descartadas

- **Solo el proxy de Coolify, sin Nginx:** Traefik no sirve ficheros ni conoce el *fallback* de cada aplicación. El reparto y las cabeceras irían en etiquetas de Coolify: menos legibles, sin `nginx -t` en la CI y atadas a Coolify.
- **El *Auto Deploy* de Coolify:** despliega aunque la CI falle, y no sabe qué versión construye.
- **Construir las imágenes en GitHub Actions y publicarlas en un registro:** compensaría si el servidor fuera justo para construir. Hoy no lo es, y añadiría un registro y sus credenciales.
- **Montar `deploy/postgres/initdb` como en desarrollo:** depende de dónde deja Coolify el código. Además, un fallo solo se notaría al crear la base, con el volumen ya inicializado y los roles sin crear.
- **Una instalación real además de la demo:** no hay ningún taller que la use. Costaría memoria del servidor y unas copias de seguridad (F9) que nadie necesita todavía.
- **Correo en la demo:** cualquiera podría enviar invitaciones a direcciones ajenas desde el servidor. A cambio, en la demo no se puede probar a aceptar una invitación.

## Consecuencias

- **El token de Coolify de la CI necesita `write`**, además de `read` y `deploy`, para poner la versión. Es un permiso amplio: el token es del equipo de Coolify, no de este recurso.
- **La imagen `web` no va atada al dominio**: el frontend llama con rutas relativas y SuperTokens usa el origen del navegador. Solo la API conoce el dominio (`APP_URL`).
- **La IP real pasa por dos proxies encadenados** (Coolify → Nginx → API). Nginx y la API se fían de las redes privadas, porque a ellos solo se llega desde contenedores.
- **Las contraseñas de los roles solo valen la primera vez**: el script corre solo con el volumen vacío. Cambiarlas después exige un `ALTER ROLE` manual.
- **La demo pierde cada noche lo que hayan hecho los visitantes**, incluidas las cuentas que hayan creado. Es lo que se busca.
- **Queda pendiente:** las copias de seguridad (F9, RNF-33) y los límites de memoria por contenedor, si el servidor se queda justo.
