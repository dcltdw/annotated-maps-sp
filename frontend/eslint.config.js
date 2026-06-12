import js from "@eslint/js";
import tseslint from "typescript-eslint";
import jsxA11y from "eslint-plugin-jsx-a11y";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { files: ["src/**/*.{ts,tsx}"], plugins: { "jsx-a11y": jsxA11y }, rules: jsxA11y.configs.recommended.rules },
  { files: ["e2e/**/*.ts", "playwright.config.ts"], languageOptions: { globals: globals.node } },
);
