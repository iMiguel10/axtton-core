import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Dos aplicaciones en un mismo proyecto (arquitectura A3): la del taller en "/" y
 * el portal del cliente en "/portal". Cada una es una entrada de Vite con su propio
 * paquete de JavaScript, así que el cliente nunca descarga el código del taller.
 *
 * En desarrollo, Vite sirve index.html para cualquier ruta desconocida. Eso vale
 * para una sola aplicación, pero aquí una URL como /portal/quotes/<taller>/<token>
 * debe servir portal/index.html, no el del taller. Este plugin hace esa elección.
 * En producción lo hará el proxy (F2).
 */
function portalFallback(): Plugin {
  return {
    name: "portal-fallback",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = req.url ?? "";
        const isPage = !url.includes(".") && !url.startsWith("/@");
        if (isPage && (url === "/portal" || url.startsWith("/portal/"))) {
          req.url = "/portal/index.html";
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), portalFallback()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      input: {
        workshop: path.resolve(import.meta.dirname, "index.html"),
        portal: path.resolve(import.meta.dirname, "portal/index.html"),
      },
    },
  },
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    // Las peticiones a /api las reenvía Vite a la API: para el navegador todo es
    // el mismo origen (localhost:5173), así que no hace falta CORS, igual que en
    // producción con un solo dominio (arquitectura §5).
    proxy: {
      "/api": process.env.API_PROXY_TARGET ?? "http://api:8000",
    },
    // Los bind mounts de Docker en Windows no propagan eventos de fichero: sin
    // polling, los cambios no se recargan dentro del contenedor.
    watch: {
      usePolling: true,
    },
  },
});
