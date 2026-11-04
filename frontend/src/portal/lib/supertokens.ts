import SuperTokens from "supertokens-web-js";
import Session from "supertokens-web-js/recipe/session";

import { queryClient } from "@/shared/lib/queryClient";

import { loginPath } from "./lastWorkshop";

/** Rutas del portal a las que se entra sin sesión: no se redirige desde ellas. */
export function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/portal/login" ||
    pathname.startsWith("/portal/login/") ||
    pathname.startsWith("/portal/access/")
  );
}

// Como en el taller: se ejecuta al importar este módulo, que main.tsx importa antes
// que nada, para que el SDK intercepte fetch y renueve la sesión ante un 401. El
// portal no usa ninguna receta de acceso del SDK: entra por nuestras rutas
// (/api/v1/portal/auth/*, decisión 0006), y el SDK solo lleva la sesión.
SuperTokens.init({
  appInfo: {
    appName: "AXTTON CORE",
    apiDomain: window.location.origin,
    apiBasePath: "/api/auth",
  },
  recipeList: [
    Session.init({
      // Cookies httpOnly: JavaScript no puede leer el token del cliente.
      tokenTransferMethod: "cookie",
      onHandleEvent: (event) => {
        // Lo cacheado es de quien estaba antes en este navegador.
        if (
          event.action === "SESSION_CREATED" ||
          event.action === "SIGN_OUT" ||
          event.action === "UNAUTHORISED"
        ) {
          queryClient.clear();
        }
        if (event.action === "UNAUTHORISED" && !isPublicPath(window.location.pathname)) {
          window.location.assign(loginPath());
        }
      },
    }),
  ],
});
