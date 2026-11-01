import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";

const web = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(join(web, "package.json"));
const temporary = mkdtempSync(join(tmpdir(), "opsdetective-artifact-probe-"));
const canary = `synthetic-dom-canary-${randomUUID()}`;

function files(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  });
}

try {
  writeFileSync(join(temporary, "artifact-probe.spec.ts"), `
import { test } from ${JSON.stringify(require.resolve("@playwright/test"))};
test('automatic artifact probe', async ({ page }) => {
  await page.setContent('<main><p>' + process.env.OPD_ARTIFACT_CANARY + '</p></main>');
  throw new Error('Controlled artifact probe failure');
});
`);
  const config = join(temporary, "probe.config.ts");
  writeFileSync(config, `
import base from ${JSON.stringify(join(web, "playwright.config.ts"))};
if (process.env.OPD_ARTIFACT_CONTROL === '1') delete process.env.PLAYWRIGHT_NO_COPY_PROMPT;
export default { ...base, testDir: ${JSON.stringify(temporary)}, testMatch: 'artifact-probe.spec.ts',
  outputDir: process.env.OPD_ARTIFACT_OUTPUT, projects: [{ name: 'privacy', use: base.projects[0].use }] };
`);
  for (const control of [false, true]) {
    const output = join(temporary, control ? "control" : "protected");
    const child = spawnSync(process.execPath, [require.resolve("@playwright/test/cli"), "test", "--config", config], {
      cwd: web, encoding: "utf8", timeout: 90000, maxBuffer: 1024 * 1024,
      env: { ...process.env, OPD_ARTIFACT_CANARY: canary,
        OPD_ARTIFACT_CONTROL: control ? "1" : "0", OPD_ARTIFACT_OUTPUT: output },
    });
    const report = `${child.stdout ?? ""}\n${child.stderr ?? ""}`;
    if (child.status !== 1 || !report.includes("Controlled artifact probe failure")) {
      throw new Error(`Browser artifact probe did not reach its controlled failure (${control ? "control" : "protected"}; ${child.status ?? child.error?.code ?? child.signal})`);
    }
    const artifacts = files(output);
    const contexts = artifacts.filter((path) => path.endsWith("error-context.md"));
    const leaked = artifacts.some((path) => readFileSync(path).includes(Buffer.from(canary)));
    if (control) {
      if (!contexts.some((path) => readFileSync(path, "utf8").includes(canary))) {
        throw new Error("Browser artifact probe control did not capture its synthetic DOM marker");
      }
    } else if (leaked || report.includes(canary) || artifacts.some((path) => /\.(png|zip|webm)$/.test(path))) {
      throw new Error("Automatic browser artifacts exposed synthetic DOM content or recorded media");
    }
  }
  console.log("Browser automatic-artifact privacy guard passed (including capture control)");
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
