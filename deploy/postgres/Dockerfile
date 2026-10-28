# Postgres de producción (compose.prod.yml): la imagen oficial con el script que
# crea los tres roles (arquitectura §4, decisión 0001). Dentro de la imagen y no
# montado desde el repositorio: Coolify construye en el servidor, y un montaje
# relativo dependería de dónde deja el código.
#
# Como en desarrollo, el script SOLO corre con el volumen vacío: en producción,
# cambiarlo no cambia nada de una base ya creada (un rol nuevo es un paso manual).
FROM postgres:17
COPY --chmod=755 initdb/ /docker-entrypoint-initdb.d/
