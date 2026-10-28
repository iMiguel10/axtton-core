# Tres etapas: `base` con lo común, `prod` (compose.prod.yml la pide con
# `target: prod`) y `dev`, la última, que es la que construye compose.yml al no
# pedir ninguna.
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Librerías de sistema de WeasyPrint (A9, A14): sin ellas, `import weasyprint`
# falla al cargar Pango. Y una tipografía: la imagen slim no trae ninguna, y sin
# fuentes el PDF sale con cuadrados en lugar de letras. En F3 las tipografías
# viajarán con la plantilla, para que el PDF no dependa de la imagen.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Usuario no privilegiado, dueño de /app y del .venv para poder ejecutar
# `uv add` y escribir cachés dentro del contenedor.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir /app \
    && chown appuser:appuser /app

WORKDIR /app
USER appuser
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000


# Producción (arquitectura §9, decisión 0004): sin las dependencias de desarrollo
# ni las pruebas, y sin --reload.
FROM base AS prod

COPY --chown=appuser:appuser pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-dev --no-install-project

COPY --chown=appuser:appuser alembic.ini entrypoint.sh ./
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser app ./app

RUN chmod +x /app/entrypoint.sh

# Como en dev, al final: cambiarla no invalida la caché de las capas de arriba.
ARG APP_VERSION=dev
ARG APP_COMMIT=
ENV APP_VERSION=$APP_VERSION \
    APP_COMMIT=$APP_COMMIT

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

# Las migraciones (entrypoint.sh) y uvicorn. --no-proxy-headers: la IP real la
# decide core/client_ip.py con TRUSTED_PROXIES; uvicorn no debe reescribirla
# antes por su cuenta.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--workers", "2"]


FROM base AS dev

# Primero solo los ficheros de dependencias: mientras no cambien, Docker
# reutiliza esta capa y no vuelve a instalar nada al tocar el código.
COPY --chown=appuser:appuser pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-install-project

COPY --chown=appuser:appuser . .

RUN chmod +x /app/entrypoint.sh

# La versión (GET /api/v1/meta): la pasa la CI desde la etiqueta de git y el
# commit (--build-arg). Al final, para que cambiarla no invalide la caché de
# las capas de arriba.
ARG APP_VERSION=dev
ARG APP_COMMIT=
ENV APP_VERSION=$APP_VERSION \
    APP_COMMIT=$APP_COMMIT

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
