import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

test("registers a service, verifies real telemetry and revokes its token", async ({ page }, info) => {
  test.setTimeout(120000);
  const file = process.env.TEST_ENV_FILE;
  if (!file) throw new Error("A generated test environment is required");
  const env = Object.fromEntries(readFileSync(file, "utf8").split("\n").map((line) => {
    const index = line.indexOf("=");
    return [line.slice(0, index), line.slice(index + 1)];
  }));
  const base = info.project.use.baseURL!;
  const login = await fetch(`${base}/api/v1/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: env.ADMIN_EMAIL, password: env.ADMIN_PASSWORD }),
    signal: AbortSignal.timeout(10000),
  }).catch(() => { throw new Error("Test login failed"); });
  expect(login.status).toBe(200);
  const cookies = login.headers.getSetCookie().map((header) => {
    const [name, value] = header.split(";")[0].split("=");
    return { name, value, url: base, httpOnly: name === "session_token", sameSite: "Lax" as const };
  });
  await page.context().addCookies(cookies).catch(() => { throw new Error("Test session setup failed"); });
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", {
    value: { writeText: async () => undefined }, configurable: true,
  }));
  await page.goto("/");
  const setup = page.getByRole("region", { name: "Services", exact: true });
  await setup.getByRole("button", { name: "Connect a service", exact: true }).click();
  await setup.getByLabel("Project", { exact: true }).selectOption("new");
  const projectName = `Onboarding ${info.project.name} ${Date.now()}`;
  const serviceName = `Synthetic orders with a long service name for narrow screen setup ${info.project.name} ${Date.now()}`;
  await setup.getByLabel("New project name", { exact: true }).fill(projectName);
  await setup.getByLabel("Telemetry source", { exact: true }).selectOption("sdk");
  await setup.getByLabel("Service name", { exact: true }).fill(serviceName);
  const registration = page.waitForResponse((response) => response.url().endsWith("/api/v1/services") && response.request().method() === "POST");
  await setup.getByRole("button", { name: "Register and continue", exact: true }).click();
  const service = await (await registration).json();
  await expect(setup.getByRole("heading", { name: serviceName, exact: true })).toBeVisible();
  const minted = page.waitForResponse((response) => response.url().endsWith(`/services/${service.id}/tokens`) && response.request().method() === "POST");
  await setup.getByRole("button", { name: "Create ingestion token", exact: true }).click();
  const created = await (await minted).json();
  await expect(setup.locator(".secret-value")).toHaveCount(0);
  await setup.getByRole("button", { name: "Copy new token", exact: true }).click();
  await expect(setup.getByRole("button", { name: "Token copied", exact: true })).toBeVisible();
  await setup.getByRole("button", { name: "I’ve saved the token", exact: true }).click();
  await expect(setup.getByRole("button", { name: "Show token", exact: true })).toHaveCount(0);
  await setup.getByRole("button", { name: "Test connection", exact: true }).click();
  await expect(setup.getByText("Waiting for telemetry", { exact: true })).toBeVisible();

  const exportMetrics = async () => {
    const attributes = [{ key: "http.route", value: { stringValue: "/orders" } },
      { key: "http.response.status_code", value: { intValue: "200" } }];
    const timeUnixNano = (BigInt(Date.now()) * BigInt(1000000)).toString();
    return fetch("http://127.0.0.1:4318/v1/metrics", {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${created.token}` },
      body: JSON.stringify({ resourceMetrics: [{ scopeMetrics: [{ metrics: [
        { name: "demo.http.requests", unit: "{request}", sum: { aggregationTemporality: 2, isMonotonic: true,
          dataPoints: [{ attributes, timeUnixNano, asInt: "5" }] } },
      ] }] }] }), signal: AbortSignal.timeout(10000),
    }).then((response) => response.status).catch(() => 0);
  };
  expect(await exportMetrics()).toBe(200);
  await expect.poll(async () => {
    await setup.getByRole("button", { name: "Test connection", exact: true }).click();
    await expect(setup.getByRole("button", { name: "Test connection", exact: true })).toBeEnabled();
    return setup.getByText("Telemetry received", { exact: true }).isVisible();
  }, { timeout: 40000, intervals: [5000, 5000, 10000, 10000] }).toBe(true);
  await setup.getByRole("link", { name: "View service health", exact: true }).click();
  await expect(page.locator("#health-project")).toHaveValue(service.project_id);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  if (process.env.TEST_SCREENSHOT_DIR) {
    mkdirSync(process.env.TEST_SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.TEST_SCREENSHOT_DIR, `onboarding-${info.project.name}.png`), fullPage: true });
  }
  await setup.getByRole("button", { name: "Revoke", exact: false }).click();
  await setup.getByRole("button", { name: "Confirm revoke", exact: true }).click();
  await expect(setup.getByText(/Revoked · Created/)).toBeVisible();
  await expect(setup.getByRole("button", { name: "Test connection", exact: true })).toBeDisabled();
  await expect.poll(exportMetrics, { timeout: 25000, intervals: [5000] }).toBe(401);
  await setup.getByRole("button", { name: "Close setup", exact: true }).click();
  await setup.getByRole("button", { name: `Set up ${serviceName} development`, exact: true }).click();
  await expect(setup.getByRole("button", { name: "Show token", exact: true })).toHaveCount(0);
  await page.route("**/api/v1/services/*/tokens", (route) => route.fulfill({ status: 401, json: { detail: "Session expired" } }));
  await setup.getByRole("button", { name: "Refresh token list", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  await expect(page.locator(".login").getByRole("alert")).toContainText("Your session ended");
});
