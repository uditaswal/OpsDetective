import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execute = promisify(execFile);

test("the demo SDK reaches real health cards and separates application from collection failure", { tag: "@live-monitor" }, async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "Shared demo lifecycle runs once; responsive states have separate coverage");
  test.setTimeout(720000);
  const project = process.env.TEST_COMPOSE_PROJECT;
  const file = process.env.TEST_ENV_FILE;
  const started = Number(process.env.TEST_STACK_STARTED_AT);
  if (!Number.isSafeInteger(started) || started <= 0 || started > Date.now() || Date.now() - started >= 300000) {
    throw new Error("The live M1 gate requires a fresh Compose-start timestamp in TEST_STACK_STARTED_AT");
  }
  if (!project || !/^opsdetective-(ci|gate)(-[a-z0-9]+)?$/.test(project) || !file || basename(file) !== `${project}.env`) {
    throw new Error("The live M1 gate requires an explicitly named disposable Compose project and matching generated environment");
  }
  const env = Object.fromEntries(readFileSync(file, "utf8").split("\n").map((line) => {
    const index = line.indexOf("="); return [line.slice(0, index), line.slice(index + 1)];
  }));
  if (env.ADMIN_EMAIL !== "admin@example.invalid" || env.DEMO_FAULTS_ENABLED !== "true" || env.DEMO_INGEST_TOKEN) {
    throw new Error("The live M1 gate requires synthetic credentials, enabled demo faults and an initially token-free demo");
  }
  const root = resolve(__dirname, "../../..");
  const composeArgs = ["compose", "--env-file", resolve(file), "-f", join(root, "infra/docker-compose.yml"), "-p", project];
  async function compose(args: string[], token?: string) {
    const childEnv = { ...process.env };
    delete childEnv.DEMO_INGEST_TOKEN;
    if (token) childEnv.DEMO_INGEST_TOKEN = token;
    await execute("docker", [...composeArgs, ...args], { cwd: root, env: childEnv, timeout: 150000, maxBuffer: 1024 * 1024 })
      .catch(() => { throw new Error("Disposable demo service operation failed"); });
  }
  const recreate = ["up", "-d", "--no-deps", "--force-recreate", "--wait", "--wait-timeout", "90", "demo-app"];
  const base = info.project.use.baseURL!;
  const login = await fetch(`${base}/api/v1/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: env.ADMIN_EMAIL, password: env.ADMIN_PASSWORD }), signal: AbortSignal.timeout(10000),
  }).catch(() => { throw new Error("Gate login failed"); });
  expect(login.status).toBe(200);
  const csrf = (await login.json().catch(() => { throw new Error("Gate login response unreadable"); })).csrf_token;
  const cookies = login.headers.getSetCookie().map((header) => {
    const [name, value] = header.split(";")[0].split("=");
    return { name, value, url: base, httpOnly: name === "session_token", sameSite: "Lax" as const };
  });
  await page.context().addCookies(cookies).catch(() => { throw new Error("Gate session setup failed"); });
  const cookie = cookies.map(({ name, value }) => `${name}=${value}`).join("; ");
  async function call(path: string, body: object, method = "POST") {
    const deadline = Date.now() + 65000;
    while (true) {
      const response = await fetch(`${base}/api/v1${path}`, {
        method, headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, Cookie: cookie },
        body: method === "DELETE" ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(10000),
      }).catch(() => { throw new Error("Gate API request failed"); });
      if (response.status === 429 && path === "/demo/faults" && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        continue;
      }
      if (!response.ok) throw new Error("Gate API request rejected");
      return;
    }
  }
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", {
    value: { writeText: async () => undefined }, configurable: true,
  }));
  let serviceId = "";
  let tokenId = "";
  let token = "";
  let collectorStopped = false;
  let faultActive = false;
  let revoked = false;
  try {
    await page.goto("/");
    const setup = page.getByRole("region", { name: "Services", exact: true });
    await setup.getByRole("button", { name: "Connect a service", exact: true }).click();
    await setup.getByLabel("Project", { exact: true }).selectOption("new");
    await setup.getByLabel("New project name", { exact: true }).fill(`Live monitor gate ${Date.now()}`);
    await setup.getByLabel("Telemetry source", { exact: true }).selectOption("demo");
    const name = `Live synthetic orders ${Date.now()}`;
    await setup.getByLabel("Service name", { exact: true }).fill(name);
    const registered = page.waitForResponse((response) => response.url().endsWith("/api/v1/services") && response.request().method() === "POST");
    await setup.getByRole("button", { name: "Register and continue", exact: true }).click();
    const service: { id: string; project_id: string } = await (await registered).json().catch(() => { throw new Error("Service response unreadable"); });
    serviceId = service.id;
    const minted = page.waitForResponse((response) => response.url().endsWith(`/services/${serviceId}/tokens`) && response.request().method() === "POST");
    await setup.getByRole("button", { name: "Create ingestion token", exact: true }).click();
    const created: { id: string; token: string } = await (await minted).json().catch(() => { throw new Error("Token response unreadable"); });
    tokenId = created.id; token = created.token;
    expect(typeof token === "string" && token.length > 32).toBe(true);
    await setup.getByRole("button", { name: "Copy new token", exact: true }).click();
    await setup.getByRole("button", { name: "I’ve saved the token", exact: true }).click();
    await expect(setup.getByRole("button", { name: "Show token", exact: true })).toHaveCount(0);
    await setup.getByRole("link", { name: "View service health", exact: true }).click();
    await compose(recreate, token);
    const card = page.getByRole("article", { name: `${name} health`, exact: true });
    const remaining = 300000 - (Date.now() - started);
    expect(remaining > 0).toBe(true);
    await expect(card.getByText("Healthy", { exact: true })).toBeVisible({ timeout: remaining });
    const values = await card.locator(".signals dd").allTextContents();
    expect(Number.parseFloat(values[0]) > 0).toBe(true);
    expect(Number.parseFloat(values[1])).toBe(0);
    const [p50, p95] = values[2].split("/").map((value) => Number.parseFloat(value));
    expect(p50 > 0 && p50 <= p95 && p95 < 500).toBe(true);
    await expect(card.getByText("Passing", { exact: true })).toBeVisible();
    await expect(card.getByText("Collection: Connected", { exact: true })).toBeVisible();
    expect(Date.now() - started).toBeLessThan(300000);
    await expect(page.getByText("Live updates", { exact: true })).toBeVisible();
    await setup.getByRole("button", { name: "Test connection", exact: true }).click();
    await expect(setup.getByText("Telemetry received", { exact: true })).toBeVisible();
    if (process.env.TEST_SCREENSHOT_DIR) {
      mkdirSync(process.env.TEST_SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({ path: join(process.env.TEST_SCREENSHOT_DIR, "live-monitor-gate.png"), fullPage: true });
    }
    faultActive = true;
    await call("/demo/faults", { mode: "http_500", duration_seconds: 60 });
    await expect(card.getByText("Degraded", { exact: true })).toBeVisible({ timeout: 60000 });
    await expect(card.getByText("Collection: Connected", { exact: true })).toBeVisible();
    await expect(card.getByText("Passing", { exact: true })).toBeVisible();
    await call("/demo/faults", { mode: "off", duration_seconds: 5 }); faultActive = false;
    const stream = `**/api/v1/projects/${service.project_id}/health/stream`;
    await page.route(stream, (route) => route.abort());
    await page.getByRole("button", { name: "Refresh health", exact: true }).click();
    await expect(page.getByText("Polling every 10 seconds", { exact: true })).toBeVisible({ timeout: 15000 });
    collectorStopped = true;
    await compose(["stop", "collector"]);
    await expect(card.getByText("Collection: Unavailable", { exact: true })).toBeVisible({ timeout: 45000 });
    await expect(card.getByText("Disconnected", { exact: true })).toBeVisible();
    await expect(card).toContainText("application health is unknown");
    await compose(["up", "-d", "--wait", "--wait-timeout", "60", "collector"]); collectorStopped = false;
    await page.unroute(stream);
    await page.getByRole("button", { name: "Refresh health", exact: true }).click();
    await expect(page.getByText("Live updates", { exact: true })).toBeVisible({ timeout: 20000 });
    await expect(card.getByText("Collection: Connected", { exact: true })).toBeVisible({ timeout: 90000 });
    await setup.getByRole("button", { name: /^Revoke token / }).click();
    await setup.getByRole("button", { name: "Confirm revoke", exact: true }).click();
    await expect(setup.getByText(/Revoked · Created/)).toBeVisible(); revoked = true;
    await expect.poll(async () => fetch("http://127.0.0.1:4318/v1/metrics", {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: "{}", signal: AbortSignal.timeout(10000),
    }).then((response) => response.status).catch(() => 0), { timeout: 25000, intervals: [5000] }).toBe(401);
    await expect(card.getByText("Collection: Stale", { exact: true })).toBeVisible({ timeout: 90000 });
    await expect(card.getByText("Disconnected", { exact: true })).toBeVisible();
    await call("/auth/logout", {});
    await expect(page.locator(".login").getByRole("alert")).toContainText("Your session ended", { timeout: 15000 });
  } finally {
    try {
      if (collectorStopped) await compose(["up", "-d", "--wait", "--wait-timeout", "60", "collector"]);
    } finally {
      try { await compose(recreate); }
      finally {
        try { if (faultActive) await call("/demo/faults", { mode: "off", duration_seconds: 5 }); }
        finally {
          try { if (tokenId && !revoked) await call(`/services/${serviceId}/tokens/${tokenId}`, {}, "DELETE"); }
          finally { token = ""; }
        }
      }
    }
  }
});
