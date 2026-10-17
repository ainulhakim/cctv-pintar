#!/usr/bin/env bash
# Provision awal di server "rumah": buat file .env dengan SECRET_KEY acak.
# Aman dijalankan berulang: kalau .env sudah ada, tidak diubah.
#
# Pemakaian:
#   bash scripts/provision_rumah.sh
#   ADMIN_PW='sandi-pilihan-saya' bash scripts/provision_rumah.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  echo "SKIP: .env sudah ada di $(pwd) — tidak diubah."
  exit 0
fi

SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
ADMIN_PW="${ADMIN_PW:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')}"

cat > .env <<EOF
# Dibuat otomatis oleh scripts/provision_rumah.sh — JANGAN commit
APP_ENV=development
SECRET_KEY=${SECRET}
ADMIN_USER=admin
ADMIN_PASSWORD=${ADMIN_PW}

DATABASE_URL=sqlite:////home/ainul/cctv-pintar/data/cctv.db
MEDIAMTX_HLS_BASE=http://127.0.0.1:8888
MEDIAMTX_API=http://127.0.0.1:9997
TZ_NAME=Asia/Jakarta
SESSION_MAX_AGE=43200
# Set 1 setelah diakses lewat HTTPS (Fase 7)
COOKIE_SECURE=0
EOF

chmod 600 .env
echo "BUAT: $(pwd)/.env (perm 600)"
echo "ADMIN_USER=admin"
echo "ADMIN_PASSWORD=${ADMIN_PW}"
