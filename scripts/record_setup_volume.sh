#!/usr/bin/env bash
# record_setup_volume.sh — siapkan "volume rekaman" dengan ukuran yang DIDEKLARASIKAN.
#
# Kenapa loopback image, bukan langsung folder di root disk?
#   * Kuota rekaman jadi HARD LIMIT di level filesystem: recorder tidak mungkin
#     "ngamuk" dan menghabiskan disk sistem, apa pun bug-nya.
#   * Ukuran bisa diatur/diubah tanpa repartisi: cukup ganti angka GB.
#   * Kalau mau dihapus, cukup umount + hapus 1 berkas (tidak menyentuh data lain).
#
# Pemakaian (di server rumah, butuh sudo):
#   sudo ./record_setup_volume.sh --size-gb 300 --path /srv/cctv-rec/rec.img --mount /srv/cctv-rec
#   sudo ./record_setup_volume.sh --size-gb 500 --path /srv/cctv-rec/rec.img --mount /srv/cctv-rec --grow
#
# Catatan: --size-gb adalah ukuran MAKSIMAL yang boleh dipakai rekaman, bukan
# ukuran disk. Sisakan selalu >= 15% ruang bebas untuk sistem.

set -euo pipefail

UKURAN_GB=300
IMG=/srv/cctv-rec/rec.img
MOUNT=/srv/cctv-rec
GROW=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --size-gb) UKURAN_GB="$2"; shift 2 ;;
    --path)    IMG="$2"; shift 2 ;;
    --mount)   MOUNT="$2"; shift 2 ;;
    --grow)    GROW=1; shift ;;
    *) echo "argumen tidak dikenal: $1" >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "!! jalankan sebagai root (sudo)" >&2
  exit 1
fi

SISA_GB=$(df -BG --output=avail "$(dirname "$MOUNT")" | tail -1 | tr -dc '0-9')
BUTUH_GB=$(( UKURAN_GB + 5 ))
if [[ "$GROW" -eq 0 && "$SISA_GB" -lt "$BUTUH_GB" ]]; then
  echo "!! ruang tidak cukup: butuh ${UKURAN_GB}G (kuota) + 5G cadangan, tersedia ${SISA_GB}G" >&2
  echo "   kurangi --size-gb, atau tambahkan/ pasang disk lain untuk volume rekaman." >&2
  exit 1
fi

mkdir -p "$MOUNT"

if [[ ! -f "$IMG" ]]; then
  echo ">> buat image ${UKURAN_GB}G (sparse) di $IMG"
  truncate -s "${UKURAN_GB}G" "$IMG"
  mkfs.ext4 -q -F -L cctv-rec "$IMG"
elif [[ "$GROW" -eq 1 ]]; then
  echo ">> perbesar image ke ${UKURAN_GB}G"
  truncate -s "${UKURAN_GB}G" "$IMG"
  e2fsck -f -y "$IMG" >/dev/null || true
  resize2fs "$IMG"
else
  echo ">> image sudah ada: $IMG (pakai --grow untuk memperbesar)"
fi

if ! mountpoint -q "$MOUNT"; then
  mount -o loop,noatime "$IMG" "$MOUNT"
fi

mkdir -p "$MOUNT"/* 2>/dev/null || true

FSTAB_LINE="$IMG  $MOUNT  ext4  loop,noatime,nofail  0  0"
if ! grep -qs "$IMG" /etc/fstab; then
  echo ">> daftarkan ke /etc/fstab"
  echo "$FSTAB_LINE" >> /etc/fstab
fi

echo ">> selesai"
df -h "$MOUNT" | tail -1
echo ">> kuota yang dipakai aplikasi (RECORD_QUOTA_GB) harus <= ${UKURAN_GB}G"
