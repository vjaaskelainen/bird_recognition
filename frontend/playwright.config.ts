import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  testMatch: "*.spec.ts",
  use: { baseURL: "http://127.0.0.1:4173", channel: process.env.PW_CHANNEL },
  webServer: {
    command: "node e2e/stub-server.ts",
    url: "http://127.0.0.1:4173/v1/health",
    reuseExistingServer: false,
  },
});
