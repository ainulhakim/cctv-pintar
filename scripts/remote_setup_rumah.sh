#!/usr/bin/env bash
# Jalankan DI SERVER RUMAH. Idempotent.
# Memasang: cloudflared (bila belum ada), konfigurasi tunnel, dan 2 unit systemd
# (cctv-pintar.service + cloudflared-cctv.service).
#
# Pemakaian:
#   SUDO_PASS=<PASSWORD-SSH> bash scripts/remote_setup_rumah.sh
set -euo pipefail

cd "$(dirname "$0")/.."
SUDO_PASS="${SUDO_PASS:-}"
CRED_FILE="<TUNNEL-ID>.json"

sudo_do() {
  if [[ -n "$SUDO_PASS" ]]; then
    echo "$SUDO_PASS" | sudo -S "$@"
  else
    sudo "$@"
  fi
}

echo ">> 1. cloudflared"
if ! command -v cloudflared >/dev/null 2>&1; then
  curl -fsSL -o /tmp/cloudflared.deb \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  sudo_do dpkg -i /tmp/cloudflared.deb
fi
cloudflared --version

echo ">> 2. konfigurasi tunnel"
mkdir -p "$HOME/.cloudflared"
if [[ ! -f "$HOME/.cloudflared/cctv-pintar.yml" ]]; then
  cp deploy/cloudflared-cctv.yml.example "$HOME/.cloudflared/cctv-pintar.yml"
  echo "   dibuat: $HOME/.cloudflared/cctv-pintar.yml"
else
  echo "   sudah ada: $HOME/.cloudflared/cctv-pintar.yml"
fi
if [[ -f "$HOME/.cloudflared/${CRED_FILE}" ]]; then
  chmod 600 "$HOME/.cloudflared/${CRED_FILE}"
  echo "   kredensial tunnel OK: ${CRED_FILE}"
else
  echo "   PERINGATAN: kredensial tunnel belum ada: $HOME/.cloudflared/${CRED_FILE}"
fi

echo ">> 3. unit systemd"
sudo_do cp deploy/cctv-pintar.service /etc/systemd/system/cctv-pintar.service
sudo_do cp deploy/cloudflared-cctv.service /etc/systemd/system/cloudflared-cctv.service
sudo_do systemctl daemon-reload
sudo_do systemctl enable --now cctv-pintar.service cloudflared-cctv.service

echo ">> 4. verifikasi"
sleep 3
systemctl is-active cctv-pintar.service cloudflared-cctv.service || true
ss -ltnp 2>/dev/null | grep -E ':8090' || echo "   PERINGATAN: tidak ada yang listen di 8090"
curl -s -o /dev/null -w "   app via IP tailnet : %{http_code}\n" http://<IP-TAILNET>:8090/healthz || true
echo ">> selesai"
