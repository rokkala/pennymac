// Catches what the bundler does not: undefined identifiers, hooks called conditionally, unused code.
import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import hooks from "eslint-plugin-react-hooks";

export default [
  { ignores: ["dist/**", "dist-demo/**", "node_modules/**"] },
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: { ecmaVersion: 2023, sourceType: "module", globals: { ...globals.browser }, parserOptions: { ecmaFeatures: { jsx: true } } },
    settings: { react: { version: "18.3" } },
    plugins: { react, "react-hooks": hooks },
    rules: {
      ...js.configs.recommended.rules,
      "react/jsx-uses-vars": "error",
      "react/jsx-uses-react": "error",
      "react/jsx-no-undef": "error",
      "react/jsx-key": "error",
      "react-hooks/rules-of-hooks": "error",
      "no-unused-vars": ["error", { varsIgnorePattern: "^_|^React$", argsIgnorePattern: "^_", caughtErrors: "none" }],
      "no-empty": ["error", { allowEmptyCatch: true }],
    },
  },
];
