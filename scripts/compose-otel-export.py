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
                                    'name': 'Synthetic demo', 'environment': 'demo', 'probe_name': 'demo'}, csrf)
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


SERVICE_HEALTH = """
import json
import os
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

api = 'http://localhost:8000'
opener = build_opener(HTTPCookieProcessor(CookieJar()))
def call(path, body=None, csrf=''):
    request = Request(api + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json', 'X-CSRF-Token': csrf})
    with opener.open(request, timeout=5) as response:
        return json.load(response)
csrf = call('/api/v1/auth/login', {'email': os.environ['ADMIN_EMAIL'],
                                   'password': os.environ['ADMIN_PASSWORD']})['csrf_token']
def wait_for(predicate, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        data = call('/api/v1/services/' + SERVICE_ID + '/health')
        if predicate(data):
            return data
        time.sleep(2)
    raise AssertionError('Service health state: ' + data['status'] + ' / collection: ' + data['collection_status'])

def set_fault(mode):
    deadline = time.monotonic() + 65
    while True:
        try:
            return call('/api/v1/demo/faults', {'mode': mode, 'duration_seconds': 60}, csrf)
        except HTTPError as error:
            if error.code != 429 or time.monotonic() >= deadline:
                raise
            time.sleep(2)

if EXPECT_COLLECTION_FAILURE:
    data = wait_for(lambda row: row['collection_status'] == 'unavailable', 30)
    assert data['status'] == 'disconnected'
    assert data['availability'] is None and data['error_rate_percent'] is None
else:
    data = wait_for(lambda row: row['status'] == 'healthy')
    assert data['collection_status'] == 'connected' and data['availability'] is True, 'Configured probe or collection was not available'
    assert data['request_rate_per_minute'] > 0 and data['latency_p95_ms'] < 500
    started = time.monotonic()
    call('/api/v1/projects/' + PROJECT_ID + '/health')
    assert time.monotonic() - started < 2, 'Dashboard health request exceeded two seconds'
    with opener.open(api + '/api/v1/projects/' + PROJECT_ID + '/health/stream', timeout=5) as response:
        assert response.headers['Content-Type'].startswith('text/event-stream')
        while True:
            line = response.readline().decode()
            if line.startswith('data: '):
                event = json.loads(line[6:])
                assert any(row['id'] == SERVICE_ID for row in event['services'])
                break
    try:
        set_fault('http_500')
        data = wait_for(lambda row: row['status'] == 'degraded' and row['error_rate_percent'] >= 5)
        assert data['collection_status'] == 'connected' and data['availability'] is True, 'Configured probe or collection was not available'
    finally:
        set_fault('off')
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
                health_script = (f"SERVICE_ID = {created['service_id']!r}\n"
                                 f"PROJECT_ID = {created['project_id']!r}\n")
                checked = subprocess.run([*compose, "exec", "-T", "api", "python", "-"],
                    input=health_script + "EXPECT_COLLECTION_FAILURE = False\n" + SERVICE_HEALTH,
                    text=True, capture_output=True, check=False)
                if checked.returncode != 0:
                    detail = next((line for line in checked.stderr.splitlines()
                                   if line.startswith("AssertionError:")), "request failed")
                    raise AssertionError(f"Live service health check failed: {detail}")
                try:
                    subprocess.run([*compose, "stop", "collector"], check=True, capture_output=True)
                    checked = subprocess.run([*compose, "exec", "-T", "api", "python", "-"],
                        input=health_script + "EXPECT_COLLECTION_FAILURE = True\n" + SERVICE_HEALTH,
                        text=True, capture_output=True, check=False)
                    if checked.returncode != 0:
                        raise AssertionError("Collection outage was not separated from application health")
                finally:
                    subprocess.run([*compose, "up", "-d", "--wait", "--wait-timeout", "60", "collector"],
                                   check=True, capture_output=True)
                print("Compose SDK storage, healthy/degraded signals, SSE and collection outage checks passed")
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
