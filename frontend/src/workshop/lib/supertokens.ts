import SuperTokens from "supertokens-web-js";
import EmailPassword from "supertokens-web-js/recipe/emailpassword";
import Session from "supertokens-web-js/recipe/session";

import { queryClient } from "@/shared/lib/queryClient";

import { keepOnlyUser } from "./drafts";

/** Rutas a las que se entra sin sesión: no se redirige al login desde ellas. */
export function isPublicPath(pathname: string): boolean {
  return (
    ["/login", "/forgot-password", "/reset-password"].includes(pathname) ||
    pathname.startsWith("/superadmin-invitations/") ||
    pathname.startsWith("/invitations/")
  );
}

// Se ejecuta al importar este módulo, que main.tsx importa ANTES que nada: el SDK
// intercepta fetch para añadir lo necesario y renovar la sesión ante un 401. Una
// petición lanzada antes de init() saldría sin interceptar.
SuperTokens.init({
  appInfo: {
    appName: "AXTTON CORE",
    // Un solo dominio: la API está en el mismo origen que la web (arquitectura §5).
    apiDomain: window.location.origin,
    apiBasePath: "/api/auth",
  },
  recipeList: [
    Session.init({
      // Explícito aunque sea el valor por defecto: el backend acepta también
      // tokens en cabecera (apps móviles), pero el navegador usa SIEMPRE cookies
      // httpOnly, que JavaScript no puede leer.
      tokenTransferMethod: "cookie",
      onHandleEvent: (event) => {
        // La caché de TanStack Query sobrevive al cambio de usuario: sin esto, la
        // siguiente persona de este navegador vería datos de la anterior. Al
        // crear la sesión también: lo cacheado antes de entrar dice "sin sesión".
        if (
          event.action === "SESSION_CREATED" ||
          event.action === "SIGN_OUT" ||
          event.action === "UNAUTHORISED"
        ) {
          queryClient.clear();
        }
        // Los borradores de quien usó antes este dispositivo, fuera. Si su sesión
        // caducó y vuelve a entrar la misma persona, los suyos siguen (RNF-22).
        if (event.action === "SESSION_CREATED") {
          void Session.getUserId()
            .then(keepOnlyUser)
            .catch(() => undefined);
        }
        if (event.action === "UNAUTHORISED" && !isPublicPath(window.location.pathname)) {
          window.location.assign("/login");
        }
      },
    }),
    EmailPassword.init(),
  ],
});
