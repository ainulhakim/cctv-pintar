#!/bin/bash
# relay_rtsp.sh — dijalankan DI MacBook: tarik RTSP kamera kantor, dorong ke MediaMTX rumah.
#
# Arsitektur (tanpa membuka port apa pun ke internet):
#   Tapo (LAN kantor) --RTSP--> ffmpeg MacBook --ssh -L--> MediaMTX rumah:8554/camkantor
#
# Varian ini menambahkan SUPERVISI: kalau tunnel ssh mati atau ffmpeg berhenti,
# keduanya dijalankan ulang otomatis. Tanpa ini ffmpeg bisa "hidup" tetapi
# socket-nya CLOSE_WAIT sehingga viewer menampilkan layar blank.
#
# Pemakaian:
#   CAM_USER=nafiri CAM_PASS=12345678 bash relay_rtsp.sh
#   CAM_PATH=stream1 (HD 1080p) | stream2 (default, 640x360)
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
RETRY_DELAY="${RETRY_DELAY:-5}"

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

SSH_PID=""
FF_PID=""

bersihkan() {
  [[ -n "$FF_PID" ]] && kill "$FF_PID" 2>/dev/null
  [[ -n "$SSH_PID" ]] && kill "$SSH_PID" 2>/dev/null
}
trap 'bersihkan; exit 0' INT TERM EXIT

while true; do
  # 1. tunnel: MacBook 127.0.0.1:28554 -> rumah 127.0.0.1:8554 (MediaMTX)
  ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15 \
      -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N \
      -L 127.0.0.1:${LOCAL_PORT}:127.0.0.1:8554 \
      "${REMOTE_USER}@${REMOTE_HOST}" &
  SSH_PID=$!
  sleep 3

  if ! kill -0 "$SSH_PID" 2>/dev/null; then
    echo "$(date '+%H:%M:%S') !! tunnel ssh gagal, ulangi dalam ${RETRY_DELAY}s"
    sleep "$RETRY_DELAY"; continue
  fi

  echo "$(date '+%H:%M:%S') >> sumber ${CAM_IP}/${CAM_PATH} -> rumah 8554/${TARGET_PATH}"

  # 2. ffmpeg: tarik RTSP Tapo, dorong ke MediaMTX lewat tunnel lokal.
  #    -fflags +genpts / -use_wallclock_as_timestamps mengatasi DTS tidak monoton
  #    dari firmware Tapo (penyebab video tersendat).
  "$FFMPEG" -hide_banner -nostdin -loglevel error \
    -rtsp_transport tcp -fflags +genpts -use_wallclock_as_timestamps 1 \
    -i "$SRC" \
    -c:v copy -an \
    -f rtsp -rtsp_transport tcp \
    "rtsp://127.0.0.1:${LOCAL_PORT}/${TARGET_PATH}" &
  FF_PID=$!

  # 3. tunggu salah satu mati, lalu jalankan ulang semuanya
  while kill -0 "$SSH_PID" 2>/dev/null && kill -0 "$FF_PID" 2>/dev/null; do
    sleep 5
  done

  echo "$(date '+%H:%M:%S') !! ffmpeg/tunnel berhenti, mulai ulang dalam ${RETRY_DELAY}s"
  bersihkan
  sleep "$RETRY_DELAY"
  SSH_PID=""; FF_PID=""
done