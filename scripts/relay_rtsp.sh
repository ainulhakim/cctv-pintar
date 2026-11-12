#!/bin/bash
# relay_rtsp.sh — jalankan di MacBook: tarik RTSP kamera LAN kantor, kirim ke rumah.
#
# Pakai `ssh -R`: server rumah mendapat listener 127.0.0.2:8555 yang diteruskan
# kembali ke MacBook, lalu ffmpeg MacBook mendorong video ke RTSP MediaMTX rumah
# (127.0.0.1:8554/camkantor). Tidak perlu membuka port apa pun ke internet.
set -uo pipefail

REMOTE_USER="${REMOTE_USER:-ainul}"
REMOTE_HOST="${REMOTE_HOST:-100.116.211.47}"
REMOTE_DIR="${REMOTE_DIR:-/home/ainul/cctv-pintar}"
KEY="${KEY:-/tmp/relay_key}"
FFMPEG="${FFMPEG:-/opt/homebrew/bin/ffmpeg}"

# kredensial Camera Account Tapo (bukan akun cloud TP-Link)
CAM_USER="${CAM_USER:-}"
CAM_PASS="${CAM_PASS:-}"
CAM_IP="${CAM_IP:-192.168.1.19}"
CAM_PATH="${CAM_PATH:-stream1}"      # stream1 = HD, stream2 = SD
TARGET_PATH="${TARGET_PATH:-camkantor}"

RELAY_PORT=8555

if [[ -z "$CAM_USER" || -z "$CAM_PASS" ]]; then
  echo "!! isi CAM_USER dan CAM_PASS (Camera Account Tapo)" >&2
  exit 2
fi

# URL-encode kredensial (aman untuk '@', ':', dll.)
python3 - "$CAM_USER" "$CAM_PASS" "$CAM_IP" "$CAM_PATH" <<'PY' > /tmp/relay_url.txt
import sys, urllib.parse
u, p, ip, path = sys.argv[1:5]
print("rtsp://%s:%s@%s:554/%s" % (urllib.parse.quote(u, safe=""), urllib.parse.quote(p, safe=""), ip, path))
PY
SRC="$(cat /tmp/relay_url.txt)"

# tunnel: rumah:127.0.0.2:8555 -> MacBook:28554 -> MediaMTX rumah:8554
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=20 \
    -N -R 127.0.0.2:${RELAY_PORT}:127.0.0.1:28554 \
    -L 127.0.0.1:28554:127.0.0.1:8554 \
    "${REMOTE_USER}@${REMOTE_HOST}" &
SSH_PID=$!
trap 'kill $SSH_PID 2>/dev/null' EXIT
sleep 3

echo ">> relay: rumah 127.0.0.2:${RELAY_PORT} -> MacBook -> MediaMTX 127.0.0.1:8554/${TARGET_PATH}"
echo ">> sumber: rtsp://${CAM_IP}:554/${CAM_PATH}"

"$FFMPEG" -hide_banner -nostdin -loglevel warning \
  -rtsp_transport tcp -i "$SRC" \
  -c:v copy -an -f rtsp -rtsp_transport tcp \
  "rtsp://127.0.0.1:28554/${TARGET_PATH}"