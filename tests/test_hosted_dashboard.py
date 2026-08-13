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


def test_hosted_compose_uses_isolated_dashboard_and_no_host_port():
    text = (ROOT / 'deploy' / 'compose.hosted.yml').read_text()
    assert 'dashboard:' in text
    assert 'app.dashboard_server:app' in text
    assert 'SIGNER_ENABLED: "false"' in text
    assert 'cloudflared:' in text
    assert 'CLOUDFLARE_TUNNEL_TOKEN:?set CLOUDFLARE_TUNNEL_TOKEN' in text
    assert 'ports:' not in text
    assert 'JUPITER_API_KEY' not in text
    assert 'HELIUS_API_KEY' not in text
    assert 'GOPLUS_ACCESS_TOKEN' not in text


def test_hosted_launcher_keeps_internal_api_private_and_routes_tunnel_to_dashboard():
    hosted = (ROOT / 'deploy' / 'start-hosted.sh').read_text()
    forward = (ROOT / 'deploy' / 'compose.forward.yml').read_text()
    assert 'CLOUDFLARE_TUNNEL_TOKEN' in hosted
    assert 'SIGNER_ENABLED != false' in hosted
    assert 'export SIGNER_ENABLED=false' in hosted
    assert 'http://dashboard:8080' in hosted
    assert 'http://api:8000' not in hosted
    assert 'up -d --build dashboard cloudflared' in hosted
    assert '127.0.0.1:8000:8000' in forward


def test_example_env_never_contains_real_tunnel_token():
    text = (ROOT / 'deploy' / '.env.forward.example').read_text()
    assert 'CLOUDFLARE_TUNNEL_TOKEN=' in text
    line = next(line for line in text.splitlines() if line.startswith('CLOUDFLARE_TUNNEL_TOKEN='))
    assert line == 'CLOUDFLARE_TUNNEL_TOKEN='
