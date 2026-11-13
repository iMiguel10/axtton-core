# Despliegue

AXTTON CORE se despliega en **Coolify** con `compose.prod.yml` ([decisión 0004](../decisiones/0004-produccion-en-coolify.md)). Coolify construye las imágenes en el servidor y pone el HTTPS; la CI decide cuándo se despliega.

Hoy hay una sola instalación: **la demo**, en `https://axtton.imigueldev.duckdns.org` ([datos de demostración](demo.md)).

## Qué hay en producción

| Servicio | Imagen | Para qué |
|---|---|---|
| `web` | `deploy/web/` | Nginx con el taller (`/`) y el portal (`/portal`) compilados; reenvía `/api` a la API. El único con dominio |
| `api` | `backend/`, etapa `prod` | Aplica las migraciones al arrancar y sirve la API |
| `worker` | la misma que `api`, con otro comando | Los trabajos en segundo plano y las tareas programadas (F5, arquitectura §8). No aplica migraciones: arranca cuando `api` está sana. Está sano si SAQ lo ve vivo en Valkey (`saq app.worker.settings --check`) |
| `db` | `deploy/postgres/` | Postgres 17 con los tres roles (arquitectura §4) |
| `supertokens` + `supertokens-db` | oficiales | Autenticación |
| `valkey` | oficial | Límite de peticiones (RNF-06) y la cola del worker. Guarda en disco (`appendonly`): reiniciarlo no pierde lo encolado |

Ninguno publica puertos en el servidor.

## Cómo llega un cambio a producción

1. Un PR se fusiona en `main` ([versionado](versionado.md)).
2. La CI pasa los jobs de siempre y, además, `prod-images`, que construye las imágenes de producción y comprueba Nginx y `compose.prod.yml`.
3. El job `deploy` (`deploy/coolify-deploy.sh`):
    - no hace nada si `main` ya avanzó, porque lo desplegará la CI del commit nuevo;
    - pone en Coolify `APP_VERSION` y `APP_COMMIT`, que se pasan al construir las imágenes;
    - pide el despliegue y espera a que termine;
    - comprueba que `/api/v1/meta` responde esa versión y ese commit.

Si el job falla, el log de Coolify dice por qué. Mientras el despliegue nuevo no arranca, sigue sirviendo el anterior.

## Montarlo desde cero

### En Coolify

1. **Un recurso nuevo** en un proyecto (por ejemplo, "AXTTON CORE", entorno `production`): *Public Repository* → `https://github.com/iMiguel10/axtton-core`, rama `main`, *Build Pack* **Docker Compose** y fichero `/compose.prod.yml`.
2. **El dominio:** en el servicio `web`, `https://axtton.imigueldev.duckdns.org` (puerto 80). Ningún otro servicio lleva dominio.
3. **Las variables** (*Environment Variables*): las de `.env.prod.example`. Cada contraseña y clave, distinta y generada con `openssl rand -hex 32`. Para la demo, además, `DEMO_SEED_ENABLED=true` y `DEMO_PORTAL_ENTRY=true` (entrar en el portal como un cliente de la demo, que no tiene correo; [demo](demo.md#el-portal-del-cliente)). Ninguna de las dos en una instalación de verdad. Con correo, `SMTP_HOST` y las demás `SMTP_*`: `SMTP_SECURITY` es `starttls` si no se dice nada (el puerto 587), o `tls` con el 465. Con cifrado pedido y un servidor que no lo ofrece, no se envía en claro: el correo falla (F5 paso 3).
4. **Desactiva el *Auto Deploy*** (*Advanced*): el despliegue lo pide la CI.
5. **El primer despliegue**, a mano desde el panel (*Deploy*).
6. **Carga la demo** la primera vez: en el contenedor `api` (*Terminal*), `python -m app.scripts.seed_demo`.
7. **Tu superadministrador**, en el mismo terminal: `python -m app.scripts.create_superadmin <tu-email>`, que pide la contraseña. La demo no trae ninguno (sería público), y este sobrevive a las recargas.
8. **La tarea programada** (*Scheduled Tasks*), en el contenedor `api`, cada noche (`0 4 * * *`):

    ```bash
    python -m app.scripts.seed_demo --purge-other-accounts
    ```

### Un token de Coolify para la CI

En Coolify, *Keys & Tokens* → *API tokens*: un token con los permisos **read**, **write** y **deploy**.

### En GitHub

En *Settings → Secrets and variables → Actions*:

| Tipo | Nombre | Valor |
|---|---|---|
| Secreto | `COOLIFY_URL` | La dirección del panel de Coolify |
| Secreto | `COOLIFY_TOKEN` | El token anterior |
| Secreto | `COOLIFY_APP_UUID` | El identificador del recurso (sale en su URL del panel) |
| Variable | `PRODUCTION_URL` | `https://axtton.imigueldev.duckdns.org` |

Sin `PRODUCTION_URL`, el job `deploy` no hace nada: un fork, o una instalación que no la tenga, no despliega.

## Probar la pila de producción en local

Con un `.env.prod` aparte (una copia de `.env.prod.example` con `APP_URL=http://localhost:8080` y las contraseñas rellenas) y la web publicada solo para la prueba:

```bash
docker compose -p axtton-prod -f compose.prod.yml -f compose.prod.local.yml --env-file .env.prod up -d --build
```

`compose.prod.local.yml` publica `web` en el puerto 8080. Para borrarla: `docker compose -p axtton-prod down -v`.

## Trampas

- **Las contraseñas de los roles solo valen la primera vez**: `deploy/postgres` crea los roles con el volumen vacío. Cambiarlas después en Coolify no cambia las de la base de datos: hay que hacer `ALTER ROLE … PASSWORD …` con el superusuario y después cambiar la variable.
- **Compose lee solo el `.env` de la carpeta**: en local, sin `--env-file`, `compose.prod.yml` tomaría el `.env` de desarrollo.
- **Coolify reescribe `compose.prod.yml`** antes de pasárselo a Docker Compose, y una lista vacía le llega como un mapa vacío: `entrypoint: []` hizo fallar el primer despliegue del worker (F5) con `services.worker.entrypoint must be a null`, aunque `docker compose config` en local y en la CI lo daba por bueno. En ese fichero no se escribe ninguna lista ni mapa vacío; el worker lleva su comando entero en `entrypoint`.
- **La IP real pasa por dos proxies** (Coolify y Nginx). Si delante de Coolify se pone un túnel, hay que volver a comprobar que la API recibe la IP del visitante y no la del túnel (RNF-06).
