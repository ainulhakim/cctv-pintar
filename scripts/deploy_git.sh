#!/usr/bin/env bash
# deploy_git.sh — deploy CCTV Pintar dari Hermes: push ke GitHub -> server rumah pull.
#
# Alur (menggantikan rsync):
#   1. pastikan working tree bersih
#   2. git push origin <branch>
#   3. ssh ke rumah, jalankan scripts/pull_deploy.sh (git pull + restart + health check)
#
# Pemakaian:
#   ./scripts/deploy_git.sh
#   RSSH_PASS=<PASSWORD-SSH> ./scripts/deploy_git.sh
#   RSSH_PASS=<PASSWORD-SSH> RUN_TESTS=1 ./scripts/deploy_git.sh   # sekalian pytest+smoke di rumah
set -euo pipefail

REMOTE_USER="${REMOTE_USER:-ainul}"
REMOTE_HOST="${REMOTE_HOST:-<IP-TAILNET>}"
REMOTE_DIR="${REMOTE_DIR:-/home/ainul/cctv-pintar}"
BRANCH="${BRANCH:-main}"
RSSH_PASS="${RSSH_PASS:-}"
RUN_TESTS="${RUN_TESTS:-0}"

cd "$(cd "$(dirname "$0")/.." && pwd)"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "!! working tree belum bersih — commit dulu:"
  git status --short
  exit 1
fi

echo ">> push ke GitHub (origin/$BRANCH)"
git push origin "$BRANCH"
HEAD_SHA="$(git rev-parse --short HEAD)"
echo ">> HEAD: $HEAD_SHA"

SSH=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "${REMOTE_USER}@${REMOTE_HOST}")
if [[ -n "$RSSH_PASS" ]]; then
  SSH=(sshpass -p "$RSSH_PASS" "${SSH[@]}")
fi

echo ">> rumah: pull_deploy.sh"
"${SSH[@]}" "cd ${REMOTE_DIR} && SUDO_PASS='${RSSH_PASS}' RUN_TESTS='${RUN_TESTS}' bash scripts/pull_deploy.sh"

echo ">> verifikasi SHA di rumah vs Hermes"
"${SSH[@]}" "cd ${REMOTE_DIR} && git rev-parse --short HEAD && git log --oneline -1 | cat"
echo ">> Hermes: $HEAD_SHA"
