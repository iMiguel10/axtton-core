/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** La etiqueta de git sin la "v" (0.3.0); la pasa la CI al compilar. */
  readonly VITE_APP_VERSION?: string;
  /** El commit compilado, abreviado. */
  readonly VITE_APP_COMMIT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
