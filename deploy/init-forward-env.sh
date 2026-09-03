#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
TARGET="deploy/.env.forward"
EXAMPLE="deploy/.env.forward.example"

if [ -e "$TARGET" ]; then
  echo "$TARGET already exists; refusing to overwrite it." >&2
  exit 1
fi

command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to generate deployment secrets." >&2
  exit 1
}

[ -f "$EXAMPLE" ] || {
  echo "Missing $EXAMPLE." >&2
  exit 1
}

cp "$EXAMPLE" "$TARGET"
chmod 600 "$TARGET"

python3 - "$TARGET" <<'PY'
from pathlib import Path
from secrets import token_urlsafe
import sys

path = Path(sys.argv[1])
text = path.read_text()
replacements = {
    "POSTGRES_PASSWORD=replace-with-a-long-random-password": f"POSTGRES_PASSWORD={token_urlsafe(36)}",
    "FORWARD_INGEST_SECRET=replace-with-a-separate-long-random-secret": f"FORWARD_INGEST_SECRET={token_urlsafe(48)}",
    "CONTROL_DB_PASSWORD=": f"CONTROL_DB_PASSWORD={token_urlsafe(36)}",
    "OWNER_CONTROL_API_TOKEN=": f"OWNER_CONTROL_API_TOKEN={token_urlsafe(48)}",
    "DASHBOARD_DB_PASSWORD=": f"DASHBOARD_DB_PASSWORD={token_urlsafe(36)}",
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"initializer expected template line is missing: {old.split('=', 1)[0]}")
    text = text.replace(old, new, 1)
path.write_text(text)
PY

chmod 600 "$TARGET"

cat <<'EOF'
Created deploy/.env.forward with generated internal secrets and mode 600.

Generated locally on this VPS:
  - PostgreSQL application password
  - forward-ingest secret
  - dedicated owner-control database password
  - private owner-control API token
  - separate dashboard read-only database password

Required to start the dedicated Telegram control worker:
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
  - TELEGRAM_OWNER_USER_ID

Can be added later before Solana M6G/M6H starts:
  - HELIUS_API_KEY
  - JUPITER_API_KEY

Can be added later before publishing the dashboard through Cloudflare:
  - CLOUDFLARE_TUNNEL_TOKEN

Optional research/security enrichment:
  - GOPLUS_ACCESS_TOKEN

Do NOT add a wallet private key, seed phrase, mnemonic, owner-vault credential, exchange withdrawal key or signer secret.
EOF
