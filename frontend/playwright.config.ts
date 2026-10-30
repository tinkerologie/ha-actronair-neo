import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests/browser",
  use: { baseURL: "http://127.0.0.1:4178" },
  webServer: {
    command: "node scripts/serve-harness.mjs",
    url: "http://127.0.0.1:4178",
    reuseExistingServer: false,
  },
  reporter: "list",
});
