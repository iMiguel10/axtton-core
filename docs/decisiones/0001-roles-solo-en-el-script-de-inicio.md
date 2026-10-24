# 0001 — Los roles de base de datos se crean solo en el script de inicio

- **Fecha:** 2026-10-23
- **Estado:** aceptada

## Contexto

La arquitectura (§9) preveía crear los tres roles (`axtton_owner`, `axtton_app` y `axtton_platform`) en dos sitios:

- en el script de inicio de Postgres, para el entorno nuevo;
- y también, de forma idempotente, en la primera migración de Alembic, para cubrir las bases de datos que ya existen, porque el script de inicio solo se ejecuta con el volumen vacío.

Al construirlo en F0 la segunda parte resulta imposible sin romper el modelo de roles. Las migraciones se conectan como `axtton_owner`, que a propósito no es superusuario. Y en PostgreSQL solo un superusuario puede crear un rol con `BYPASSRLS`, que es justo lo que necesita `axtton_platform`.

## Decisión

Los roles, la base de pruebas y los permisos por defecto se crean **solo** en `deploy/postgres/initdb/01-roles.sh`, ejecutado como el superusuario de la imagen. Las migraciones crean tablas, funciones y políticas, y nunca roles.

## Alternativas descartadas

- **Dar a `axtton_owner` el atributo `SUPERUSER`** para que la migración pueda crear roles: un superusuario se salta RLS siempre, y el dueño de las tablas dejaría de estar sujeto a `FORCE ROW LEVEL SECURITY`. Rompe la prueba R1 de la arquitectura.
- **Dar a `axtton_owner` el atributo `CREATEROLE`**: no basta, porque desde PostgreSQL 16 un rol con `CREATEROLE` solo puede conceder los atributos que él mismo tiene, y `axtton_owner` no tiene `BYPASSRLS`.
- **Ejecutar las migraciones como superusuario**: las tablas tendrían otro dueño y la aplicación tendría a mano unas credenciales que lo pueden todo.

## Consecuencias

- **En desarrollo**, cambiar el script de inicio obliga a recrear el volumen: `docker compose down -v` (se pierden los datos de desarrollo).
- **En producción**, el script corre una vez, al crear el volumen en el primer despliegue (F2). Un rol que se añada después exige un paso manual con el superusuario, que el manual de despliegue debe recoger.
- El superusuario de la imagen solo existe para ese script: ningún servicio de la aplicación lo usa.
