from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "compose.alerts.yml"
START = ROOT / "deploy" / "start-alerts.sh"
RUNBOOK = ROOT / "docs" / "OWNER_ALERTS.md"


def test_alert_launcher_parses_with_posix_sh():
    result = subprocess.run(["sh", "-n", str(START)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_alert_compose_has_no_live_or_provider_credentials():
    text = COMPOSE.read_text()
    assert 'profiles: ["alerts"]' in text
    assert 'SIGNER_ENABLED: "false"' in text
    assert 'TELEGRAM_BOT_TOKEN:' in text
    assert 'TELEGRAM_CHAT_ID:' in text
    assert 'ports: []' in text
    assert 'cap_drop: [ALL]' in text
    assert 'no-new-privileges:true' in text
    assert 'HELIUS_API_KEY' not in text
    assert 'JUPITER_API_KEY' not in text
    assert 'GOPLUS_ACCESS_TOKEN' not in text
    assert 'CLOUDFLARE_TUNNEL_TOKEN' not in text
    assert 'PRIVATE_KEY' not in text
    assert 'SEED' not in text
    assert '/execute' not in text


def test_alert_launcher_requires_credentials_but_never_echoes_token():
    text = START.read_text()
    assert 'TELEGRAM_BOT_TOKEN is required' in text
    assert 'TELEGRAM_CHAT_ID is required' in text
    assert 'SIGNER_ENABLED must remain false' in text
    assert 'export SIGNER_ENABLED=false' in text
    assert 'echo "$TELEGRAM_BOT_TOKEN"' not in text
    assert '--profile alerts' in text


def test_alert_runbook_keeps_alerting_separate_from_trading():
    text = RUNBOOK.read_text()
    assert 'do **not** trade, sign, transfer funds' in text
    assert 'notification transport failure never contaminates or stops' in text
    assert 'GREEN-1_CANDIDATE' in text
    assert 'cannot enable live trading' in text
    assert 'python -m app.alert_ops test' in text
