#!/usr/bin/env bash
# pull_deploy.sh — deploy CCTV Pintar DI SERVER RUMAH lewat git.
#
# Menggantikan alur rsync: folder /home/ainul/cctv-pintar sekarang adalah
# **clone git** (read-only, HTTPS publik) sehingga tidak ada dua versi kode.
#
# Idempotent:
#   - kalau folder BELUM repo git  -> di-inisialisasi jadi clone dari GitHub
#     (file .env, .venv, data/, deploy/mediamtx.yml tidak tersentuh)
#   - kalau sudah repo git         -> git pull --ff-only
#
# Pemakaian di rumah:
#   cd ~/cctv-pintar
#   SUDO_PASS=<PASSWORD-SSH> bash scripts/pull_deploy.sh
#
# Opsi:
#   RUN_TESTS=1   jalankan pytest + smoke sebelum restart service
#   BRANCH=main   branch yang dilacak (default main)
#   SERVICE=cctv-pintar
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ainulhakim/cctv-pintar.git}"
BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-cctv-pintar}"
SUDO_PASS="${SUDO_PASS:-}"
HEALTH_URL="${HEALTH_URL:-http://<IP-TAILNET>:8090/healthz}"
RUN_TESTS="${RUN_TESTS:-0}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

echo ">> dir   : $DIR"
echo ">> repo  : $REPO_URL (branch $BRANCH)"

if [[ -d .git ]]; then
  BEFORE="$(git rev-parse --short HEAD)"
  echo ">> sebelum: $BEFORE"
  echo ">> fetch + pull --ff-only"
  git remote set-url origin "$REPO_URL"
  git fetch --prune origin "$BRANCH"
  if ! git pull --ff-only origin "$BRANCH"; then
    echo "!! pull --ff-only gagal (ada perubahan lokal / divergen) -> paksa samakan dengan GitHub"
    git status --short || true
    git reset --hard "origin/$BRANCH"
  fi
else
  echo ">> belum repo git -> inisialisasi clone (file .env/.venv/data dibiarkan apa adanya)"
  git init -q -b "$BRANCH"
  git remote add origin "$REPO_URL" 2>/dev/null || git remote set-url origin "$REPO_URL"
  BEFORE="-"
  git fetch --prune origin "$BRANCH"
  # Buat ref branch dulu supaya HEAD valid (pada clone baru HEAD masih "unborn"),
  # baru reset --hard: berkas yang ada di repo ditimpa, berkas ter-gitignore tetap aman.
  git update-ref "refs/heads/$BRANCH" "refs/remotes/origin/$BRANCH" 2>/dev/null || true
  git reset --hard "origin/$BRANCH"
  git branch -q --set-upstream-to="origin/$BRANCH" "$BRANCH" 2>/dev/null || true
fi

git config pull.ff only
git config advice.detachedHead false

AFTER="$(git rev-parse --short HEAD)"
echo ">> sekarang: $AFTER  ($(git log --oneline -1 | cat))"
if [[ "$BEFORE" == "$AFTER" ]]; then
  echo ">> tidak ada perubahan kode"
else
  echo ">> kode diperbarui: $BEFORE -> $AFTER"
  echo ">> berkas berubah:"
  git diff --name-status "$BEFORE" "$AFTER" 2>/dev/null || true
fi

if [[ "$RUN_TESTS" == "1" ]]; then
  PY=".venv/bin/python"
  [[ -x "$PY" ]] || PY="python3"
  echo ">> pytest"
  "$PY" -m pytest -q
  echo ">> smoke"
  "$PY" scripts/smoke.py
fi

if systemctl list-unit-files --type=service | grep -q "^${SERVICE}\.service"; then
  echo ">> restart service '$SERVICE'"
  if [[ -n "$SUDO_PASS" ]]; then
    echo "$SUDO_PASS" | sudo -S systemctl restart "$SERVICE"
  else
    sudo systemctl restart "$SERVICE"
  fi
  sleep 2
  systemctl is-active "$SERVICE"
  echo ">> health: $HEALTH_URL"
  if curl -fsS --max-time 10 "$HEALTH_URL"; then echo; else echo "!! health check gagal — periksa: journalctl -u $SERVICE -n 50 --no-pager"; fi
else
  echo "!! unit ${SERVICE}.service tidak ditemukan — lewati restart"
fi

echo ">> selesai: $AFTER"
