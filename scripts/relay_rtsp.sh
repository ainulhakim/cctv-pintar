#!/bin/bash
# relay_rtsp.sh — dijalankan DI MacBook: tarik RTSP kamera kantor, dorong ke MediaMTX rumah.
#
# Arsitektur (tanpa membuka port apa pun ke internet):
#   Tapo (LAN kantor) --RTSP--> ffmpeg MacBook --ssh -L--> MediaMTX rumah:8554/camkantor
#
# MacBook menghubungkan dirinya ke rumah lewat Tailscale, lalu memakai forward
# lokal 127.0.0.1:28554 -> rumah:127.0.0.1:8554. ffmpeg cukup push ke localhost.
#
# Pemakaian:
#   CAM_USER=nafiri CAM_PASS=12345678 bash relay_rtsp.sh
#   CAM_PATH=stream1 ... (HD 1080p; default stream2 = 640x360)
set -uo pipefail

REMOTE_USER="${REMOTE_USER:-ainul}"
REMOTE_HOST="${REMOTE_HOST:-100.116.211.47}"
KEY="${KEY:-/tmp/relay_key}"
FFMPEG="${FFMPEG:-/opt/homebrew/bin/ffmpeg}"

CAM_USER="${CAM_USER:-}"
CAM_PASS="${CAM_PASS:-}"
CAM_IP="${CAM_IP:-192.168.1.19}"
CAM_PATH="${CAM_PATH:-stream2}"
TARGET_PATH="${TARGET_PATH:-camkantor}"
LOCAL_PORT="${LOCAL_PORT:-28554}"

if [[ -z "$CAM_USER" || -z "$CAM_PASS" ]]; then
  echo "!! isi CAM_USER dan CAM_PASS (Camera Account Tapo, bukan akun cloud)" >&2
  exit 2
fi

SRC=$(CAM_USER="$CAM_USER" CAM_PASS="$CAM_PASS" CAM_IP="$CAM_IP" CAM_PATH="$CAM_PATH" python3 - <<'PY'
import os, urllib.parse
u = urllib.parse.quote(os.environ["CAM_USER"], safe="")
p = urllib.parse.quote(os.environ["CAM_PASS"], safe="")
print("rtsp://%s:%s@%s:554/%s" % (u, p, os.environ["CAM_IP"], os.environ["CAM_PATH"]))
PY
)

# tunnel: MacBook 127.0.0.1:28554 -> rumah 127.0.0.1:8554 (MediaMTX)
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=20 \
    -o ExitOnForwardFailure=yes -N \
    -L 127.0.0.1:${LOCAL_PORT}:127.0.0.1:8554 \
    "${REMOTE_USER}@${REMOTE_HOST}" &
SSH_PID=$!
trap 'kill $SSH_PID 2>/dev/null' EXIT
sleep 3

echo ">> sumber  : rtsp://${CAM_IP}:554/${CAM_PATH} (user ${CAM_USER})"
echo ">> tujuan  : rumah 127.0.0.1:8554/${TARGET_PATH} via tunnel lokal :${LOCAL_PORT}"

# -c:v copy: tanpa re-encode (Tapo sudah H.264) -> CPU ringan, kualitas utuh
exec "$FFMPEG" -hide_banner -nostdin -loglevel warning \
  -rtsp_transport tcp -i "$SRC" \
  -c:v copy -an \
  -f rtsp -rtsp_transport tcp \
  "rtsp://127.0.0.1:${LOCAL_PORT}/${TARGET_PATH}"