import { defineConfig } from "@playwright/test";

process.env.PLAYWRIGHT_NO_COPY_PROMPT = "1";
const baseURL = process.env.TEST_BASE_URL ?? "http://127.0.0.1:3000";
if (!["127.0.0.1", "localhost"].includes(new URL(baseURL).hostname)) {
  throw new Error("Browser tests require a loopback test server");
}

export default defineConfig({
  testDir: "./tests",
  timeout: 45000,
  workers: 1,
  retries: 0,
  reporter: "line",
  outputDir: "/tmp/opsdetective-browser-results",
  use: {
    baseURL,
    headless: true,
    trace: "off", video: "off", screenshot: "off",
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    { name: "tablet", use: { viewport: { width: 768, height: 1024 } } },
    { name: "phone", use: { viewport: { width: 390, height: 844 } } },
  ],
});
