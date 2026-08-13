from pathlib import Path
import os
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "deploy" / "init-forward-env.sh"


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_environment_initializer_parses_with_posix_sh():
    result = subprocess.run(["sh", "-n", str(INIT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_environment_initializer_generates_internal_secrets_without_external_credentials(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy(ROOT / "deploy" / ".env.forward.example", deploy / ".env.forward.example")
    shutil.copy(INIT, deploy / "init-forward-env.sh")

    result = subprocess.run(
        ["sh", "deploy/init-forward-env.sh"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    env_path = deploy / ".env.forward"
    assert env_path.exists()
    mode = os.stat(env_path).st_mode & 0o777
    assert mode == 0o600

    values = _parse_env(env_path)
    assert len(values["POSTGRES_PASSWORD"]) >= 24
    assert len(values["FORWARD_INGEST_SECRET"]) >= 32
    assert not values["POSTGRES_PASSWORD"].startswith("replace-with-")
    assert not values["FORWARD_INGEST_SECRET"].startswith("replace-with-")
    assert values["HELIUS_API_KEY"] == ""
    assert values["JUPITER_API_KEY"] == ""
    assert values["CLOUDFLARE_TUNNEL_TOKEN"] == ""
    assert values["GOPLUS_ACCESS_TOKEN"] == ""

    # Generated values must never be printed by the initializer.
    combined = result.stdout + result.stderr
    assert values["POSTGRES_PASSWORD"] not in combined
    assert values["FORWARD_INGEST_SECRET"] not in combined


def test_environment_initializer_refuses_to_overwrite_existing_real_env(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy(ROOT / "deploy" / ".env.forward.example", deploy / ".env.forward.example")
    shutil.copy(INIT, deploy / "init-forward-env.sh")
    existing = deploy / ".env.forward"
    existing.write_text("DO_NOT_REPLACE=1\n")

    result = subprocess.run(
        ["sh", "deploy/init-forward-env.sh"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert existing.read_text() == "DO_NOT_REPLACE=1\n"
    assert "refusing to overwrite" in result.stderr.lower()


def test_deployment_handoff_repeats_no_wallet_and_green_candidate_boundaries():
    text = (ROOT / "docs" / "DEPLOYMENT_HANDOFF.md").read_text()
    assert "Do **not** provide" in text
    assert "Solana/EVM private key" in text
    assert "sh deploy/init-forward-env.sh" in text
    assert "sh deploy/preflight-forward.sh" in text
    assert "sh deploy/verify-forward.sh --with-dashboard --strict" in text
    assert "GREEN-1_CANDIDATE" in text
    assert "does not activate a signer or move money" in text


def test_readme_no_longer_describes_repository_as_milestone1_only():
    text = (ROOT / "README.md").read_text()
    assert "Current mode: paper/shadow research only" in text
    assert "Hyperliquid funding/carry" in text
    assert "Polymarket structural" in text
    assert "Solana Pump baseline" in text
    assert "Dashboard V1" in text
    assert "Nothing in the current repository authorizes live capital" in text
