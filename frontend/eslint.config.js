import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  js.configs.recommended,
  {
    files: ["src/**/*.{js,jsx}"],
    plugins: {
      "react-hooks": reactHooks,
    },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        window: "readonly",
        document: "readonly",
        console: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        requestAnimationFrame: "readonly",
        cancelAnimationFrame: "readonly",
        fetch: "readonly",
        WebSocket: "readonly",
        Date: "readonly",
        Math: "readonly",
        JSON: "readonly",
        Intl: "readonly",
        String: "readonly",
        Number: "readonly",
        Object: "readonly",
        Promise: "readonly",
        Set: "readonly",
      },
    },
    rules: {
      // Core hooks correctness rules — stable, catch real bugs
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "no-unused-vars": ["warn", { varsIgnorePattern: "^_", argsIgnorePattern: "^_" }],
    },
  },
];
