#!/bin/sh
# Despliegue continuo (decisión 0004): lo llama el job `deploy` de la CI cuando un
# push a main pasa todo lo demás. Pone en Coolify la versión que se va a
# construir, pide el despliegue, espera a que termine y comprueba en
# /api/v1/meta que la API que responde es la de este commit.
#
# Variables: COOLIFY_URL, COOLIFY_TOKEN (permisos read, write y deploy: write
# para la versión, read para seguir el despliegue), COOLIFY_APP_UUID,
# PRODUCTION_URL, EXPECTED_SHA (el commit que ha pasado la CI), APP_VERSION y
# APP_COMMIT (de .github/scripts/version.sh).
#
# Coolify despliega siempre lo último de la rama, no un commit concreto: si main
# ya ha avanzado, desplegar aquí subiría un commit que esta CI no ha probado. Ese
# caso se salta sin fallar; lo despliega la CI del commit nuevo cuando pase.
set -eu

: "${COOLIFY_URL:?}" "${COOLIFY_TOKEN:?}" "${COOLIFY_APP_UUID:?}"
: "${PRODUCTION_URL:?}" "${EXPECTED_SHA:?}" "${APP_VERSION:?}" "${APP_COMMIT:?}"
# Sin barra final: con ella, las llamadas saldrían como //api/v1.
COOLIFY_URL=${COOLIFY_URL%/}
PRODUCTION_URL=${PRODUCTION_URL%/}

BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT

# api <método> <ruta> [cuerpo JSON]: deja la respuesta en $BODY y devuelve 0 si
# es 2xx, 2 si el error no se arregla repitiendo (4xx: token sin permiso, uuid
# incorrecto…) y 1 si puede ser pasajero (red, 5xx).
api() {
    if [ $# -ge 3 ]; then
        code=$(curl -sS --max-time 30 -o "$BODY" -w '%{http_code}' -X "$1" \
            -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Accept: application/json" \
            -H "Content-Type: application/json" --data "$3" \
            "$COOLIFY_URL/api/v1/$2") || code=000
    else
        code=$(curl -sS --max-time 30 -o "$BODY" -w '%{http_code}' -X "$1" \
            -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Accept: application/json" \
            "$COOLIFY_URL/api/v1/$2") || code=000
    fi
    case "$code" in
        2??) return 0 ;;
        401|403)
            echo "Coolify rechazó el token ($code) en $1 /api/v1/${2%%\?*}: necesita los permisos read, write y deploy" >&2
            return 2 ;;
        4??)
            echo "Coolify respondió $code a $1 /api/v1/${2%%\?*}: $(head -c 300 "$BODY")" >&2
            return 2 ;;
        *)
            echo "Coolify no respondió bien ($code) a $1 /api/v1/${2%%\?*}" >&2
            return 1 ;;
    esac
}

# Sin poder leer main no se sabe si este commit sigue siendo el último: no se da
# por bueno.
refs=$(git ls-remote origin refs/heads/main) || { echo "No se pudo leer main en origin" >&2; exit 1; }
head_sha=$(echo "$refs" | cut -f1)
[ -n "$head_sha" ] || { echo "origin no tiene la rama main" >&2; exit 1; }
if [ "$head_sha" != "$EXPECTED_SHA" ]; then
    echo "main ya está en $head_sha, no en $EXPECTED_SHA: lo desplegará la CI de ese commit."
    exit 0
fi

# La versión que se va a construir (decisión 0003): compose.prod.yml la pasa
# como argumento de build a web y a api.
api PATCH "applications/$COOLIFY_APP_UUID/envs/bulk" \
    "$(jq -nc --arg v "$APP_VERSION" --arg c "$APP_COMMIT" \
        '{data: [{key: "APP_VERSION", value: $v}, {key: "APP_COMMIT", value: $c}]}')" \
    || exit 1
echo "Versión $APP_VERSION ($APP_COMMIT)"

api POST "deploy?uuid=$COOLIFY_APP_UUID&force=false" || exit 1
# Un 200 que no es JSON (la página de acceso de un proxy delante del panel) no es
# una respuesta de Coolify.
deployment=$(jq -r '.deployments[0].deployment_uuid // empty' "$BODY" 2>/dev/null) \
    || { echo "Coolify respondió algo que no es JSON al pedir el despliegue" >&2; exit 1; }
[ -n "$deployment" ] || { echo "Coolify no devolvió ningún despliegue" >&2; exit 1; }
echo "Despliegue $deployment en cola"

# Construye en el servidor. Se espera hasta 30 minutos. Un fallo pasajero se
# tolera unas pocas veces seguidas; uno que no se arregla repitiendo, ninguna.
status=""
failures=0
i=0
while [ "$i" -lt 180 ]; do
    i=$((i + 1))
    sleep 10
    rc=0
    api GET "deployments/$deployment" || rc=$?
    if [ "$rc" -eq 0 ] && ! status=$(jq -r '.status' "$BODY" 2>/dev/null); then
        echo "Coolify respondió algo que no es JSON al consultar el despliegue" >&2
        rc=1
    fi
    if [ "$rc" -eq 2 ]; then
        exit 1
    elif [ "$rc" -ne 0 ]; then
        failures=$((failures + 1))
        [ "$failures" -lt 6 ] || { echo "Coolify falló 6 veces seguidas" >&2; exit 1; }
        continue
    fi
    failures=0
    case "$status" in
        finished) break ;;
        failed|cancelled*)
            echo "El despliegue terminó en '$status'; el log, en el panel de Coolify" >&2
            exit 1 ;;
    esac
done
[ "$status" = "finished" ] || { echo "El despliegue no terminó en 30 minutos" >&2; exit 1; }

# Lo que Coolify clonó de verdad. /api/v1/meta no basta: su commit es el de
# APP_COMMIT, que pone este script, no el del código construido. Si alguien
# empujó a main entre la comprobación de arriba y el clonado, Coolify construyó
# un commit que esta CI no ha probado, con la versión del anterior. Lo encontró
# qa-verifier al cerrar F2.
deployed=$(jq -r '.commit // empty' "$BODY")
if [ -z "$deployed" ]; then
    echo "::warning::Coolify no indica qué commit desplegó: no se ha podido comprobar que sea $EXPECTED_SHA"
elif [ "$deployed" != "$EXPECTED_SHA" ]; then
    echo "Coolify desplegó $deployed y no $EXPECTED_SHA (main avanzó a la vez): lo corrige la CI de ese commit" >&2
    exit 1
fi

# Lo que de verdad responde: la API recién arrancada puede tardar unos segundos
# (migraciones). Si /meta dice otro commit, Coolify construyó otra cosa.
meta=""
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    meta=$(curl -fsS --max-time 10 "$PRODUCTION_URL/api/v1/meta" 2>/dev/null) || meta=""
    if [ -n "$meta" ] && echo "$meta" | jq -e --arg v "$APP_VERSION" --arg c "$APP_COMMIT" \
        '.version == $v and .commit == $c' > /dev/null 2>&1; then
        echo "$PRODUCTION_URL responde $APP_VERSION ($APP_COMMIT)"
        exit 0
    fi
    sleep 10
done
echo "$PRODUCTION_URL/api/v1/meta no responde $APP_VERSION ($APP_COMMIT) tras el despliegue: ${meta:-sin respuesta}" >&2
exit 1
