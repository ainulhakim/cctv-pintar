#!/usr/bin/env bash
# recorder.sh — perekam satu kamera (segmen per jam, codec copy / tanpa transcode).
#
# Dijalankan oleh systemd (cctv-record@<nama>.service) dengan EnvironmentFile.
# Supervisor: kalau ffmpeg berhenti (kamera reboot, kabel lepas, WiFi putus),
# tunggu 5 detik lalu coba lagi — tanpa intervensi manual.
#
# Variabel wajib:
#   CAM_NAME   nama segmen/kamera, mis. utara
#   CAM_URL    rtsp://... kamera (pakai sub-stream!) atau rtsp://127.0.0.1:8554/<path>
# Opsional:
#   OUT_DIR          default /srv/cctv-rec
#   SEGMENT_SECONDS  default 3600 (1 jam per berkas)
#   QUALITY          label di nama berkas, default "sub"
#   SEGMENT_FORMAT   default "ts" (mpegts) — lihat catatan di bawah

set -uo pipefail

: "${CAM_NAME:?CAM_NAME belum diset}"
: "${CAM_URL:?CAM_URL belum diset}"
OUT_DIR="${OUT_DIR:-/srv/cctv-rec}"
SEGMENT_SECONDS="${SEGMENT_SECONDS:-3600}"
QUALITY="${QUALITY:-sub}"
# Kenapa default mpegts, bukan mp4:
#   Segmen mp4 baru punya "moov atom" saat berkas ditutup rapi. Kalau ffmpeg
#   mati mendadak (reboot, listrik, kamera putus), segmen yang sedang ditulis
#   jadi TIDAK bisa diputar tapi tetap memakan kuota. MPEG-TS tidak butuh
#   moov: potongan yang sempat tertulis selalu bisa diputar (VLC/ffmpeg).
SEGMENT_FORMAT="${SEGMENT_FORMAT:-ts}"
case "$SEGMENT_FORMAT" in
  ts|mpegts) SEG_EXT="ts";  SEG_FMT="mpegts"; SEG_OPTS=() ;;
  mp4)       SEG_EXT="mp4"; SEG_FMT="mp4";    SEG_OPTS=(-segment_format_options movflags=+faststart) ;;
  *) echo "!! SEGMENT_FORMAT tidak dikenal: $SEGMENT_FORMAT (pakai ts|mp4)" >&2; exit 2 ;;
esac

TUJUAN="${OUT_DIR}/${CAM_NAME}"
mkdir -p "$TUJUAN"

# Kompatibilitas ffmpeg: opsi timeout socket RTSP berbeda antar versi.
#   ffmpeg 4.x (Debian 11) -> -stimeout (mikrodetik)
#   ffmpeg 5.x+            -> -rw_timeout (mikrodetik); -stimeout sudah dihapus
FFMAJOR=$(ffmpeg -hide_banner -version 2>/dev/null | head -1 | sed -n 's/.*version n\?\([0-9]\+\)\..*/\1/p')
FFMAJOR="${FFMAJOR:-4}"
if [[ "$FFMAJOR" -ge 5 ]] && ffmpeg -hide_banner -h demuxer=rtsp 2>/dev/null | grep -q -- "-rw_timeout"; then
  TIMEOUT_OPT=(-rw_timeout 15000000)
else
  TIMEOUT_OPT=(-stimeout 15000000)
fi

echo ">> recorder ${CAM_NAME}: ${CAM_URL} -> ${TUJUAN} (segmen ${SEGMENT_SECONDS}s ${SEG_FMT}, timeout ${TIMEOUT_OPT[*]})"

while true; do
  ffmpeg -hide_banner -loglevel warning -nostdin \
    -rtsp_transport tcp "${TIMEOUT_OPT[@]}" \
    -fflags +genpts -use_wallclock_as_timestamps 1 \
    -i "$CAM_URL" \
    -c copy -an \
    -f segment -segment_time "$SEGMENT_SECONDS" \
    -segment_format "$SEG_FMT" ${SEG_OPTS[@]+"${SEG_OPTS[@]}"} \
    -reset_timestamps 1 -strftime 1 \
    "${TUJUAN}/%Y%m%d-%H%M%S_${QUALITY}.${SEG_EXT}" \
    || true
  echo "!! ${CAM_NAME}: ffmpeg berhenti (rc=$?), coba lagi 5 detik"
  sleep 5
done
