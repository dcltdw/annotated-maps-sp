import js from "@eslint/js";
import tseslint from "typescript-eslint";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    // Allow intentionally-unused args/vars when prefixed with `_` (the standard convention —
    // e.g. interface-stub params in the swappable draw adapters / test doubles).
    files: ["**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
    },
  },
  // eslint-plugin-react-hooks@7's `recommended`/`recommended-latest` presets bundle the
  // new React-Compiler ruleset (refs, set-state-in-effect, …) on top of the two classic
  // rules. Enable just the classic rules — rules-of-hooks (error) + exhaustive-deps (warn) —
  // per this hardening task; the compiler rules are out of scope.
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
  { files: ["src/**/*.{ts,tsx}"], plugins: { "jsx-a11y": jsxA11y }, rules: jsxA11y.configs.recommended.rules },
  { files: ["e2e/**/*.ts", "playwright.config.ts"], languageOptions: { globals: globals.node } },
);
