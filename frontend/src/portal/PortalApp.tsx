import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Session from "supertokens-web-js/recipe/session";

import { AppSplash } from "@/shared/components/Loading";

import { loginPath } from "./lib/lastWorkshop";

// Cada pantalla en su trozo, como en el taller: el portal se abre en el móvil
// desde un email y tiene que cargar rápido (RNF-53).
const AccessPage = lazy(() => import("./features/auth/AccessPage").then((m) => ({ default: m.AccessPage })));
const HomePage = lazy(() => import("./features/home/HomePage").then((m) => ({ default: m.HomePage })));
const NoWorkshopPage = lazy(() => import("./features/auth/NoWorkshopPage").then((m) => ({ default: m.NoWorkshopPage })));
const RequestLinkPage = lazy(() => import("./features/auth/RequestLinkPage").then((m) => ({ default: m.RequestLinkPage })));

/**
 * Portal del cliente (F4), en /portal. Se entra desde la página de un taller
 * (/portal/login/{taller}) con un enlace mágico de ese taller (decisión 0006); la
 * sesión resultante solo ve ese taller.
 */
export function PortalApp() {
  return (
    <Suspense fallback={<AppSplash />}>
      <Routes>
        <Route path="/login" element={<NoWorkshopPage />} />
        <Route path="/login/:workshopId" element={<RequestLinkPage />} />
        <Route path="/access/:workshopId" element={<AccessPage />} />
        <Route path="/*" element={<SessionGate />} />
      </Routes>
    </Suspense>
  );
}

/** Sin sesión, a pedir el enlace. Qué puede ver la sesión lo decide la API. */
function SessionGate() {
  const session = useQuery({
    queryKey: ["session-exists"],
    queryFn: () => Session.doesSessionExist(),
    staleTime: Infinity,
  });
  if (session.isPending) return <AppSplash />;
  // Sin sesión, a la entrada del último taller (o a la página sin taller).
  if (!session.data) return <Navigate to={loginPath().replace(/^\/portal/, "")} replace />;
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
