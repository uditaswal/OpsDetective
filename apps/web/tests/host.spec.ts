import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

test("host resources keep project scope and hide stale or failed measurements", async ({ page }, info) => {
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
  const csrf = (await login.json()).csrf_token;
  const cookies = login.headers.getSetCookie().map((header) => {
    const [name, value] = header.split(";")[0].split("=");
    return { name, value, url: base, httpOnly: name === "session_token", sameSite: "Lax" as const };
  });
  await page.context().addCookies(cookies).catch(() => { throw new Error("Test session setup failed"); });
  const cookie = cookies.map(({ name, value }) => `${name}=${value}`).join("; ");
  const projects: { id: string }[] = [];
  for (const suffix of ["host", "other"]) {
    const response = await fetch(`${base}/api/v1/projects`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, Cookie: cookie },
      body: JSON.stringify({ name: `Browser ${info.project.name} ${suffix} ${Date.now()}` }),
      signal: AbortSignal.timeout(10000),
    }).catch(() => { throw new Error("Test project setup failed"); });
    expect(response.status).toBe(201);
    projects.push(await response.json());
  }
  await page.goto("/");
  const host = page.getByRole("region", { name: "Host resources", exact: true });
  await page.locator("#health-project").selectOption(projects[0].id);
  await expect(host.getByText("No host assigned", { exact: true })).toBeVisible();
  let state = "connected";
  await page.route(`**/api/v1/projects/${projects[0].id}/host`, (route) => state === "error" ? route.abort() : route.fulfill({ json: {
    project_id: projects[0].id, host_id: "synthetic-host", status: state,
    observed_at: new Date().toISOString(), last_seen_at: new Date(Date.now() - (state === "stale" ? 90000 : 1000)).toISOString(),
    freshness_seconds: state === "stale" ? 90 : 1, stale_seconds: 60,
    cpu_usage_percent: state === "connected" ? 25 : null, memory_usage_percent: state === "connected" ? 75 : null,
    disk_busy_percent: state === "connected" ? 12 : null,
    memory_used_bytes: state === "connected" ? 6 * 1024 ** 3 : null, memory_total_bytes: state === "connected" ? 8 * 1024 ** 3 : null,
    detail: state === "stale" ? "Host samples are stale; resource usage is unknown." : "Whole monitoring host usage, including other processes. CPU uses a two-minute average.",
  } }));
  await host.getByRole("button", { name: "Refresh host", exact: true }).click();
  await expect(host.getByText("25.0%", { exact: true })).toBeVisible();
  await expect(host.getByText("75.0%", { exact: true })).toBeVisible();
  await expect(host.getByText("12.0%", { exact: true })).toBeVisible();
  await expect(host.getByText("6.0 GiB of 8.0 GiB", { exact: true })).toBeVisible();
  if (process.env.TEST_SCREENSHOT_DIR) {
    mkdirSync(process.env.TEST_SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.TEST_SCREENSHOT_DIR, `host-${info.project.name}.png`), fullPage: true });
  }
  state = "stale";
  await host.getByRole("button", { name: "Refresh host", exact: true }).click();
  await expect(host.getByText("Stale", { exact: true })).toBeVisible();
  await expect(host.getByText("25.0%", { exact: true })).toHaveCount(0);
  await expect(host.getByText("75.0%", { exact: true })).toHaveCount(0);
  await expect(host.getByText("12.0%", { exact: true })).toHaveCount(0);
  state = "error";
  await host.getByRole("button", { name: "Refresh host", exact: true }).click();
  await expect(host.getByRole("alert")).toContainText("Resource usage is unknown");
  await page.locator("#health-project").selectOption(projects[1].id);
  await expect(host.getByText("No host assigned", { exact: true })).toBeVisible();
  await expect(host.getByText("25.0%", { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
