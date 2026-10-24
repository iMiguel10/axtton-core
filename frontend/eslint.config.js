import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

// La regla que mantiene separadas las dos aplicaciones (arquitectura A3, §6):
// src/workshop y src/portal no se importan entre sí; lo común vive en src/shared.
const forbidImportsFrom = (other) => ({
  "no-restricted-imports": [
    "error",
    {
      patterns: [
        {
          group: [`@/${other}`, `@/${other}/*`, `**/${other}/*`],
          message: `src/${other} es otra aplicación: lo común va a src/shared.`,
        },
      ],
    },
  ],
});

export default tseslint.config(
  { ignores: ["dist"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  { files: ["src/workshop/**/*.{ts,tsx}"], rules: forbidImportsFrom("portal") },
  { files: ["src/portal/**/*.{ts,tsx}"], rules: forbidImportsFrom("workshop") },
);
