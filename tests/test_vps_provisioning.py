from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PROVISION = ROOT / "deploy" / "provision-ubuntu.sh"
CHECK = ROOT / "deploy" / "check-vps-host.sh"
RUNBOOK = ROOT / "docs" / "VPS_PROVISIONING.md"


def test_vps_shell_scripts_parse():
    for path in (PROVISION, CHECK):
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_provisioner_uses_official_docker_repo_and_does_not_embed_credentials():
    text = PROVISION.read_text()
    assert "https://download.docker.com/linux/ubuntu/gpg" in text
    assert "https://download.docker.com/linux/ubuntu" in text
    assert "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin" in text
    assert "systemctl enable --now docker" in text
    assert "24.04|26.04" in text
    assert "amd64|arm64" in text
    assert "Refusing to remove them automatically" in text
    assert "EDGE_CONFIGURE_UFW" in text
    assert "ufw allow" in text
    assert "PRIVATE_KEY" not in text
    assert "SEED_PHRASE" not in text
    assert "MNEMONIC" not in text
    assert "CLOUDFLARE_TUNNEL_TOKEN=" not in text


def test_host_check_enforces_research_vps_capacity_and_time_sync():
    text = CHECK.read_text()
    assert "EDGE_MIN_VCPU:-4" in text
    assert "EDGE_MIN_MEMORY_MB:-7000" in text
    assert "EDGE_MIN_FREE_DISK_GB:-40" in text
    assert "docker info" in text
    assert "docker compose version" in text
    assert "NTPSynchronized" in text
    assert "deploy/preflight-forward.sh" in text


def test_runbook_keeps_wallets_out_and_cloudflare_tunnel_outbound_model():
    text = RUNBOOK.read_text()
    assert "4 vCPU, 8 GB RAM, 100+ GB NVMe" in text
    assert "Cloudflare Tunnel does not require inbound HTTP/HTTPS ports" in text
    assert "Docker networking can bypass ordinary UFW expectations" in text
    assert "wallet private key" in text
    assert "owner-vault credential" in text
    assert "sh deploy/preflight-forward.sh" in text
    assert "sh deploy/verify-forward.sh --with-dashboard --strict" in text
