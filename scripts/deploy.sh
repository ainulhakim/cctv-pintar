#!/usr/bin/env bash
# Deploy CCTV Pintar: workspace Hermes -> server "rumah".
#
# Pemakaian:
#   ./scripts/deploy.sh                 # sinkron kode + restart service (kalau ada)
#   RSSH_PASS=<PASSWORD-SSH> ./scripts/deploy.sh   # pakai sshpass (non-interaktif)
#
# Catatan: file .env, data/, dan deploy/mediamtx.yml TIDAK ikut tersinkron
# (kredensial & state tetap hanya di server).
set -euo pipefail

REMOTE_USER="${REMOTE_USER:-ainul}"
REMOTE_HOST="${REMOTE_HOST:-<IP-TAILNET>}"
REMOTE_DIR="${REMOTE_DIR:-/home/ainul/cctv-pintar}"
SERVICE="${SERVICE:-cctv-pintar}"

cd "$(dirname "$0")/.."

SSH=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "${REMOTE_USER}@${REMOTE_HOST}")
if [[ -n "${RSSH_PASS:-}" ]]; then
  SSH=(sshpass -p "${RSSH_PASS}" "${SSH[@]}")
fi

echo ">> rsync -> ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude 'data/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.env' \
  --exclude 'deploy/mediamtx.yml' \
  --exclude 'deploy/cloudflared/' \
  -e "$([[ -n "${RSSH_PASS:-}" ]] && echo "sshpass -p ${RSSH_PASS} ssh -o StrictHostKeyChecking=accept-new")" \
  ./ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

echo ">> cek service '${SERVICE}'"
"${SSH[@]}" "systemctl list-unit-files | grep -q '^${SERVICE}.service' && sudo systemctl restart ${SERVICE} && systemctl is-active ${SERVICE} || echo 'service ${SERVICE} belum ada (dibuat di Fase 7)'"

echo ">> selesai"
