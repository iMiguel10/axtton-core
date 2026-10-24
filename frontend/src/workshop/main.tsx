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

import { WorkshopApp } from "./WorkshopApp";

// Antes de pintar: sin esto se vería un destello del tema claro al recargar en oscuro.
applyInitialTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <WorkshopApp />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
