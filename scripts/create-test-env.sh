#!/usr/bin/env bash
set -euo pipefail

test_env_path=${1:?provide a path for the temporary environment file}
umask 077
{
  printf 'POSTGRES_USER=opsdetective\n'
  printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)"
  printf 'POSTGRES_DB=opsdetective\n'
  printf 'ADMIN_EMAIL=admin@example.invalid\n'
  printf 'ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 32)"
  printf 'SESSION_SECRET=%s\n' "$(openssl rand -hex 32)"
  printf 'INTERNAL_API_KEY=%s\n' "$(openssl rand -hex 32)"
  printf 'DEMO_FAULTS_ENABLED=true\n'
  printf 'DEMO_CONTROL_KEY=%s\n' "$(openssl rand -hex 32)"
  printf 'DEMO_TRAFFIC_ENABLED=true\n'
  printf 'DEMO_TRAFFIC_INTERVAL_SECONDS=2\n'
  printf 'DEMO_INGEST_TOKEN=\n'
} > "$test_env_path"
