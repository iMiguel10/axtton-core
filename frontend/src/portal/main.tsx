import "@/shared/i18n/i18n";
import "@/shared/styles/global.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { applyInitialTheme } from "@/shared/components/Preferences";

import { PortalApp } from "./PortalApp";

applyInitialTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PortalApp />
  </StrictMode>,
);
