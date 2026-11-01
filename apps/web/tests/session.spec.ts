import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

test("a fresh visitor can sign in without an expired-session warning", async ({ page }, info) => {
  await page.goto("/");
  const login = page.locator(".login");
  await expect(login.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  await expect(login.getByRole("alert")).toHaveCount(0);
  if (process.env.TEST_SCREENSHOT_DIR) {
    mkdirSync(process.env.TEST_SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.TEST_SCREENSHOT_DIR, `signin-${info.project.name}.png`), fullPage: true });
  }
});

test("an unavailable startup session check offers a recovery message", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator(".login").getByRole("alert")).toContainText("Session check is unavailable");
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeEnabled();
});
