#!/bin/sh
# La versión de lo que se construye (GET /api/v1/meta y la interfaz), como
# líneas VAR=valor para $GITHUB_ENV: la última etiqueta vX.Y.Z, sin la "v", y
# el commit abreviado. Entre dos versiones, la etiqueta es la anterior y el
# commit dice qué se construyó exactamente. Necesita las etiquetas en el
# checkout (fetch-depth: 0).
set -eu
tag=$(git describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || echo v0.0.0)
echo "APP_VERSION=${tag#v}"
echo "APP_COMMIT=$(git rev-parse --short=7 HEAD)"
