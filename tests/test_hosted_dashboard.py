from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard_server import app


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_server_exposes_only_dashboard_surface():
    client = TestClient(app)
    assert client.get('/healthz').status_code == 200
    assert client.get('/dashboard').status_code == 200
    assert client.get('/signer/status').status_code == 404
    assert client.get('/venues/hyperliquid/status').status_code == 404
    assert client.post('/risk/evaluate', json={}).status_code == 404
    assert client.post('/venues/polymarket/scan').status_code == 404


def test_hosted_compose_uses_isolated_dashboard_readonly_role_and_no_host_port():
    text = (ROOT / 'deploy' / 'compose.hosted.yml').read_text()
    assert 'dashboard-db-role:' in text
    assert 'CREATE ROLE edge_dashboard LOGIN PASSWORD' in text
    assert 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO edge_dashboard' in text
    assert 'ALTER DEFAULT PRIVILEGES FOR ROLE edge' in text
    assert 'postgresql+psycopg://edge_dashboard:${DASHBOARD_DB_PASSWORD}@postgres:5432/edge' in text
    assert 'app.dashboard_server:app' in text
    assert 'SIGNER_ENABLED: "false"' in text
    assert 'cloudflared:' in text
    assert 'TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:?set CLOUDFLARE_TUNNEL_TOKEN}' in text
    assert text.count('ports: []') >= 2
    assert 'dashboard_edge:' in text
    assert 'cap_drop:' in text
    assert 'no-new-privileges:true' in text
    assert 'JUPITER_API_KEY' not in text
    assert 'HELIUS_API_KEY' not in text
    assert 'GOPLUS_ACCESS_TOKEN' not in text


def test_hosted_launcher_keeps_internal_api_private_and_routes_tunnel_to_dashboard():
    hosted = (ROOT / 'deploy' / 'start-hosted.sh').read_text()
    forward = (ROOT / 'deploy' / 'compose.forward.yml').read_text()
    assert 'DASHBOARD_DB_PASSWORD' in hosted
    assert 'CLOUDFLARE_TUNNEL_TOKEN' in hosted
    assert 'SIGNER_ENABLED != false' in hosted
    assert 'export SIGNER_ENABLED=false' in hosted
    assert 'http://dashboard:8080' in hosted
    assert 'http://api:8000' not in hosted
    assert 'dashboard-db-role dashboard cloudflared' in hosted
    assert '127.0.0.1:8000:8000' in forward


def test_example_env_never_contains_real_hosting_secrets():
    lines = (ROOT / 'deploy' / '.env.forward.example').read_text().splitlines()
    tunnel = next(line for line in lines if line.startswith('CLOUDFLARE_TUNNEL_TOKEN='))
    dashboard_db = next(line for line in lines if line.startswith('DASHBOARD_DB_PASSWORD='))
    assert tunnel == 'CLOUDFLARE_TUNNEL_TOKEN='
    assert dashboard_db == 'DASHBOARD_DB_PASSWORD='
