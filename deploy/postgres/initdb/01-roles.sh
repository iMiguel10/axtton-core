#!/bin/bash
# Roles y bases de datos de AXTTON CORE (arquitectura §4).
#
# La imagen de Postgres ejecuta los scripts de /docker-entrypoint-initdb.d SOLO
# la primera vez, con el volumen de datos vacío. Si cambias este fichero, en
# desarrollo hay que recrear el volumen: docker compose down -v.
#
# Se ejecuta como el superusuario de la imagen (POSTGRES_USER). Ese superusuario
# no lo usa nunca la aplicación: un superusuario se salta RLS siempre.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Dueño de las tablas: lo usan las migraciones. NOBYPASSRLS y, como las
    -- tablas llevan FORCE ROW LEVEL SECURITY, RLS también le aplica.
    CREATE ROLE axtton_owner LOGIN PASSWORD '${AXTTON_OWNER_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
    -- La API y el worker en su camino normal: siempre bajo RLS.
    CREATE ROLE axtton_app LOGIN PASSWORD '${AXTTON_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
    -- Solo app/platform/: el único que cruza talleres.
    CREATE ROLE axtton_platform LOGIN PASSWORD '${AXTTON_PLATFORM_PASSWORD}' NOSUPERUSER BYPASSRLS;

    ALTER DATABASE "${POSTGRES_DB}" OWNER TO axtton_owner;
EOSQL

# La base de pruebas, solo en desarrollo y en la CI: en producción
# (compose.prod.yml) POSTGRES_TEST_DB no existe.
databases="$POSTGRES_DB"
if [ -n "${POSTGRES_TEST_DB:-}" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -c"CREATE DATABASE \"${POSTGRES_TEST_DB}\" OWNER axtton_owner;"
    databases="$databases $POSTGRES_TEST_DB"
fi

# Lo mismo en la base de la aplicación y en la de pruebas.
for db in $databases; do
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-EOSQL
        ALTER SCHEMA public OWNER TO axtton_owner;
        -- Nadie más que el dueño crea objetos en el esquema.
        REVOKE CREATE ON SCHEMA public FROM PUBLIC;
        GRANT USAGE ON SCHEMA public TO axtton_app, axtton_platform;

        -- Permisos por defecto sobre lo que cree axtton_owner a partir de ahora.
        -- Las tablas append-only quitarán UPDATE y DELETE en su propia migración.
        ALTER DEFAULT PRIVILEGES FOR ROLE axtton_owner IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO axtton_app, axtton_platform;
        ALTER DEFAULT PRIVILEGES FOR ROLE axtton_owner IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO axtton_app, axtton_platform;
EOSQL
done
