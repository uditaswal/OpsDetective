"""Verify demo OTLP metrics and traces through the authenticated Compose gateway.

The service token stays in this process and the demo container environment. It is
never written to the temporary Compose environment file or command output.
"""

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REGISTER = """
import json
import os
import uuid
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener

api = 'http://localhost:8000'
opener = build_opener(HTTPCookieProcessor(CookieJar()))

def post(path, body, csrf=''):
    request = Request(api + path, data=json.dumps(body).encode(), method='POST',
                      headers={'Content-Type': 'application/json', 'X-CSRF-Token': csrf})
    with opener.open(request, timeout=10) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f'API returned {response.status}')
        return json.load(response)

login = post('/api/v1/auth/login', {'email': os.environ['ADMIN_EMAIL'],
                                     'password': os.environ['ADMIN_PASSWORD']})
csrf = login['csrf_token']
project = post('/api/v1/projects', {'name': 'OTel export ' + uuid.uuid4().hex}, csrf)
service = post('/api/v1/services', {'project_id': project['id'],
                                    'name': 'Synthetic demo', 'environment': 'demo'}, csrf)
token = post('/api/v1/services/' + service['id'] + '/tokens', {}, csrf)
print(json.dumps({'token': token['token'], 'token_id': token['id'],
                  'service_id': service['id'], 'project_id': project['id']}))
"""

STORED_METRICS = """
import json
import time
from urllib.parse import urlencode
from urllib.request import urlopen

query = '{job="otlp",service_id="' + SERVICE_ID + '",project_id="' + PROJECT_ID + '"}'
deadline = time.monotonic() + 45
while time.monotonic() < deadline:
    with urlopen('http://prometheus:9090/api/v1/query?' + urlencode({'query': query}), timeout=5) as response:
        rows = json.load(response)['data']['result']
    names = {row['metric']['__name__'] for row in rows}
    counter = any(name.startswith('demo_http_requests') and name.endswith('_total') for name in names)
    histogram = any(name.startswith('demo_http_duration') and name.endswith('_bucket') for name in names)
    if counter and histogram:
        break
    time.sleep(2)
else:
    raise AssertionError('Registered demo counter and histogram were not persisted with scoped labels')
"""


REVOKE = """
import json
import os
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener

api = 'http://localhost:8000'
opener = build_opener(HTTPCookieProcessor(CookieJar()))
login_request = Request(api + '/api/v1/auth/login',
                        data=json.dumps({'email': os.environ['ADMIN_EMAIL'],
                                         'password': os.environ['ADMIN_PASSWORD']}).encode(),
                        method='POST', headers={'Content-Type': 'application/json'})
with opener.open(login_request, timeout=10) as response:
    csrf = json.load(response)['csrf_token']
request = Request(api + '/api/v1/services/' + SERVICE_ID + '/tokens/' + TOKEN_ID,
                  method='DELETE', headers={'X-CSRF-Token': csrf})
with opener.open(request, timeout=10) as response:
    assert response.status == 200
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    compose = ["docker", "compose", "--env-file", str(args.env_file),
               "-f", "infra/docker-compose.yml", "-p", args.project]
    registered = subprocess.run(
        [*compose, "exec", "-T", "api", "python", "-"], input=REGISTER,
        text=True, capture_output=True, check=False,
    )
    if registered.returncode != 0:
        raise RuntimeError("Could not register the demo service token in the API container")
    created = json.loads(registered.stdout)
    token_env = os.environ.copy()
    token_env["DEMO_INGEST_TOKEN"] = created["token"]
    clean_env = os.environ.copy()
    clean_env.pop("DEMO_INGEST_TOKEN", None)
    recreate = [*compose, "up", "-d", "--force-recreate", "--no-deps",
                "--wait", "--wait-timeout", "90", "demo-app"]
    started = datetime.now(timezone.utc).isoformat()
    try:
        subprocess.run(recreate, env=token_env, check=True, capture_output=True, text=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            logs = subprocess.run(
                [*compose, "logs", "--no-color", "--since", started, "gateway"],
                text=True, capture_output=True, check=True,
            ).stdout
            metrics_ok = any('POST /v1/metrics HTTP/1.1" 200' in line for line in logs.splitlines())
            traces_ok = any('POST /v1/traces HTTP/1.1" 200' in line for line in logs.splitlines())
            if metrics_ok and traces_ok:
                stored = (f"SERVICE_ID = {created['service_id']!r}\n"
                          f"PROJECT_ID = {created['project_id']!r}\n" + STORED_METRICS)
                checked = subprocess.run([*compose, "exec", "-T", "api", "python", "-"],
                                         input=stored, text=True, capture_output=True, check=False)
                if checked.returncode != 0:
                    raise AssertionError("Registered demo metrics were not persisted in Prometheus")
                print("Compose demo metrics stored with scoped labels; traces accepted through Collector")
                return
            time.sleep(2)
        raise AssertionError("Demo metrics and traces did not both reach the Collector within 60 seconds")
    finally:
        try:
            subprocess.run(recreate, env=clean_env, check=True, capture_output=True, text=True)
        finally:
            revoke = (f"SERVICE_ID = {created['service_id']!r}\n"
                      f"TOKEN_ID = {created['token_id']!r}\n" + REVOKE)
            subprocess.run([*compose, "exec", "-T", "api", "python", "-"],
                           input=revoke, text=True, capture_output=True, check=True)


if __name__ == "__main__":
    main()
