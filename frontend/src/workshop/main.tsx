import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@/shared/styles.css";
import { WorkshopApp } from "./WorkshopApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <WorkshopApp />
  </StrictMode>,
);
