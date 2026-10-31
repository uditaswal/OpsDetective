import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const envFile = process.env.TEST_ENV_FILE;
if (!envFile) throw new Error("TEST_ENV_FILE must refer to a generated test environment");
const env = Object.fromEntries(readFileSync(envFile, "utf8").split("\n").map((line) => {
  const index = line.indexOf("=");
  return [line.slice(0, index), line.slice(index + 1)];
}));

test("service health separates measured failures, collection failures and polling", async ({ page }, info) => {
  const base = info.project.use.baseURL!;
  const login = await fetch(`${base}/api/v1/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: env.ADMIN_EMAIL, password: env.ADMIN_PASSWORD }),
    signal: AbortSignal.timeout(10000),
  }).catch(() => { throw new Error("Test login request failed"); });
  expect(login.status).toBe(200);
  const csrf = (await login.json()).csrf_token;
  const cookies = login.headers.getSetCookie().map((header) => {
    const [name, value] = header.split(";")[0].split("=");
    return { name, value, url: base, httpOnly: name === "session_token", sameSite: "Lax" as const };
  });
  await page.context().addCookies(cookies).catch(() => { throw new Error("Test session setup failed"); });
  const cookieHeader = cookies.map(({ name, value }) => `${name}=${value}`).join("; ");
  const create = async (path: string, data: object) => {
    const response = await fetch(`${base}/api/v1${path}`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, Cookie: cookieHeader },
      body: JSON.stringify(data), signal: AbortSignal.timeout(10000),
    }).catch(() => { throw new Error("Test record setup failed"); });
    expect(response.status).toBe(201);
    return response.json();
  };
  const projectName = `Browser ${info.project.name} ${Date.now()}`;
  const project = await create("/projects", { name: projectName });
  const service = await create("/services", { project_id: project.id, name: "Synthetic orders", environment: "demo" });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  await page.locator("#health-project").selectOption(project.id);
  const card = page.getByRole("article", { name: "Synthetic orders health" });
  await expect(card.getByText("Disconnected", { exact: true })).toBeVisible();
  await expect(card.getByText("Last seen: No recent samples", { exact: true })).toBeVisible();

  let status = "healthy";
  const data = () => ({
    project_id: project.id, observed_at: new Date().toISOString(),
    policy: { stale_seconds: 60, error_rate_percent: 5, latency_p95_ms: 500, window_seconds: 120 },
    services: [{ ...service, status, collection_status: status === "disconnected" ? "unavailable" : "connected",
      request_rate_per_minute: status === "disconnected" ? null : 30, error_rate_percent: status === "disconnected" ? null : status === "degraded" ? 20 : 0,
      latency_p95_ms: status === "disconnected" ? null : 12, availability: null,
      last_seen_at: status === "disconnected" ? null : new Date().toISOString(), freshness_seconds: status === "disconnected" ? null : 0,
      reasons: status === "disconnected" ? ["Metric collection is unavailable; application health is unknown."] : [],
    }],
  });
  // Synthetic responses exercise browser state transitions; live data is checked in Compose.
  await page.route(`**/api/v1/projects/${project.id}/health/stream`, (route) => route.abort());
  await page.route(`**/api/v1/projects/${project.id}/health`, (route) => route.fulfill({ json: data() }));
  await page.getByRole("button", { name: "Refresh health" }).click();
  await expect(page.getByText("Polling every 10 seconds", { exact: true })).toBeVisible();
  await expect(card.getByText("Healthy", { exact: true })).toBeVisible();
  await expect(card.getByText("0%", { exact: true })).toBeVisible();
  await expect(card.getByText("Bucket-approximated", { exact: true })).toBeVisible();
  status = "degraded";
  await expect(card.getByText("Degraded", { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(card.getByText("20%", { exact: true })).toBeVisible();
  status = "disconnected";
  await expect(card.getByText("Disconnected", { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(card.getByText("Collection: Unavailable", { exact: true })).toBeVisible();
  await expect(card.getByText("Last seen: Unknown", { exact: true })).toBeVisible();
  await expect(card.getByText("Healthy", { exact: true })).toHaveCount(0);
  status = "healthy";
  await page.getByRole("button", { name: "Refresh health" }).click();
  await expect(card.getByText("Healthy", { exact: true })).toBeVisible();
  await page.route(`**/api/v1/projects/${project.id}/health`, (route) => route.abort());
  await page.getByRole("button", { name: "Refresh health" }).click();
  await expect(page.getByRole("region", { name: "Service health", exact: true }).getByRole("alert")).toContainText("Updates are unavailable");
  await expect(card).toContainText("Application health is unknown");
  await expect(card.getByText("Healthy", { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.unroute(`**/api/v1/projects/${project.id}/health`);
  await page.unroute(`**/api/v1/projects/${project.id}/health/stream`);
  await page.getByRole("button", { name: "Refresh health" }).click();
  await expect(page.getByText("Live updates", { exact: true })).toBeVisible();
  await expect(card.getByText("Disconnected", { exact: true })).toBeVisible();
  if (process.env.TEST_SCREENSHOT_DIR) {
    mkdirSync(process.env.TEST_SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.TEST_SCREENSHOT_DIR, `${info.project.name}.png`), fullPage: true });
  }
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
});
