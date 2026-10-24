# Dos etapas por ahora: `base` con lo común y `dev`, la última, que es la que
# construye compose.yml al no pedir ninguna. La de producción (`prod`) llega con
# el primer despliegue (F2).
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Usuario no privilegiado, dueño de /app y del .venv para poder ejecutar
# `uv add` y escribir cachés dentro del contenedor.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir /app \
    && chown appuser:appuser /app

WORKDIR /app
USER appuser
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000


FROM base AS dev

# Primero solo los ficheros de dependencias: mientras no cambien, Docker
# reutiliza esta capa y no vuelve a instalar nada al tocar el código.
COPY --chown=appuser:appuser pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-install-project

COPY --chown=appuser:appuser . .

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
