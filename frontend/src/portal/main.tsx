// Primero SuperTokens: tiene que interceptar fetch antes de que salga ninguna petición.
import "./lib/supertokens";
import "@/shared/i18n/i18n";
import "@/shared/styles/global.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { applyInitialTheme } from "@/shared/components/Preferences";
import { queryClient } from "@/shared/lib/queryClient";

import { PortalApp } from "./PortalApp";

applyInitialTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* El portal vive en /portal: las rutas de dentro empiezan en "/". */}
      <BrowserRouter basename="/portal">
        <PortalApp />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
