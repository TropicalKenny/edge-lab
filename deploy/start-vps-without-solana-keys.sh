#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

# This launcher intentionally does not start the Solana network workers. It brings up
# everything that can be verified before Helius/Jupiter are supplied.
sh deploy/start-core-forward.sh
sh deploy/start-dashboard-local.sh
sh deploy/start-control-plane.sh
sh deploy/start-alerts.sh

cat <<'EOF'

EDGE LAB VPS BASELINE IS RUNNING

Running now:
  - PostgreSQL + migrations + backups
  - Hyperliquid paper/shadow collection
  - Polymarket paper/shadow collection
  - forward evaluator
  - frozen Solana M6G study registration (network workers idle)
  - read-only dashboard on VPS loopback :8080
  - private owner-control API on VPS loopback :8090
  - Telegram read/control worker
  - Telegram owner-alert worker

Still intentionally disabled until provider keys are added:
  - Solana launch collector
  - Solana forensic sampler
  - Solana M6G forward runner
  - M6H lifecycle observer/accounting worker

Live signer, live capital, swaps, transfers and withdrawals remain disabled.
EOF
