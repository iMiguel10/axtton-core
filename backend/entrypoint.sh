#!/bin/bash
# Aplica las migraciones pendientes y después ejecuta el comando recibido.
# Las migraciones van con MIGRATIONS_DATABASE_URL (axtton_owner); el comando,
# con DATABASE_URL (axtton_app). Son roles distintos a propósito (arquitectura §4).
set -euo pipefail

alembic upgrade head

exec "$@"
