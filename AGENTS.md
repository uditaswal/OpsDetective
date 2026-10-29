# Repository working rules

These rules apply to every change in OpsDetective. The product requirements and milestone gates are in the local, Git-ignored `docs/docs-internal` directory.

## Safety and data

- Never commit, print, log, or place secrets or personal data in images, CI output, caches, or browser bundles. Read secrets from environment variables or a secret manager. Add only placeholders to `.env.example`.
- Keep `.env*` except `.env.example`, logs, caches, build output, `node_modules`, and local internal documents out of Git and Docker contexts. Report a discovered secret so it can be rotated.
- Use synthetic demo telemetry. Do not ingest employer or customer data without authorization.
- Validate all input server-side. Use parameterized database access, tenant filters, authorization and record ownership checks, CSRF defenses, rate limits on sensitive routes, and secure headers. Never execute commands from user or model input.
- Redact evidence before it can reach an LLM. Treat telemetry and model output as untrusted; model tools must be read-only, bounded, and tenant-scoped. Never auto-remediate.

## Engineering

- Respect milestone gates in the PRD. Do not present a later-milestone stub as a completed feature.
- Keep functions typed and focused, handle failures explicitly, and add meaningful tests for behavior changes. Run lint, typecheck, tests, and builds that are available; report unavailable checks.
- Prefer maintained dependencies with pinned versions and lockfiles. Do not bypass pre-commit or CI checks. Keep Dependabot, CodeQL, and secret scanning enabled once configured.
- Make small reviewable commits with clear messages. Do not include `Co-Authored-By` or any AI attribution in commits or repository content. Do not push directly to a protected branch.
- Record implementation decisions, completed work, checks, and remaining gate items in `docs/docs-internal/pplan.md` after each change.

## Interface and documentation

- Use accessible labels, focus states, keyboard navigation, clear validation, responsive layouts, and honest empty/loading/error states. Do not invent usage metrics, testimonials, legal facts, or customer claims.
- Add legal and trust pages before public launch using user-supplied company facts. Gate nonessential tracking on consent. Add production SEO, monitoring, and performance checks when public pages are introduced.
- Document every environment variable, service, data flow, and operating limit. Keep production defaults secure; Docker socket access belongs only in the documented development profile.
