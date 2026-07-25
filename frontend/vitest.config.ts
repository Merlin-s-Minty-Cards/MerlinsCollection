import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    // The Sanity client is constructed at module load and throws without a
    // projectId. Tests never reach the network (they stub the client), but the
    // constructor still has to be satisfied.
    env: {
      NEXT_PUBLIC_SANITY_PROJECT_ID: "test-project",
      NEXT_PUBLIC_SANITY_DATASET: "test",
    },
    include: ["**/__tests__/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
    },
  },
});
