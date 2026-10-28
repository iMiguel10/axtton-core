# Imagen `web` de producción (arquitectura §9, decisión 0004): las dos
# aplicaciones compiladas (el taller en / y el portal en /portal), servidas por
# Nginx, que además reenvía /api a la API. Se construye desde la raíz del
# repositorio (compose.prod.yml, context: .).
#
# No va atada al dominio: el frontend llama a la API con rutas relativas y
# SuperTokens usa window.location.origin. El dominio solo lo conoce la API
# (APP_URL).

FROM node:24-alpine AS app
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# La versión (decisión 0003): Vite pasa al código las VITE_* del entorno.
ARG APP_VERSION=dev
ARG APP_COMMIT=
ENV VITE_APP_VERSION=$APP_VERSION \
    VITE_APP_COMMIT=$APP_COMMIT
RUN npm run build


FROM nginx:1.29-alpine
# El fichero de la imagen oficial escucha en el 80 con su propia raíz: se sustituye.
RUN rm /etc/nginx/conf.d/default.conf
COPY deploy/web/nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=app /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/healthz || exit 1
