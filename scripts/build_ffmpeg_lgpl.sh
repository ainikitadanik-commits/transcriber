#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
VENDOR="$ROOT/build/product/vendor"
VERSION="7.1"
ARCHIVE="$VENDOR/ffmpeg-$VERSION.tar.xz"
SOURCE="$VENDOR/ffmpeg-$VERSION"
OUTPUT="$VENDOR/ffmpeg"
URL="https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz"
SHA256="40973d44970dbc83ef302b0609f2e74982be2d85916dd2ee7472d30678a7abe6"

mkdir -p "$VENDOR"

if [[ ! -f "$ARCHIVE" ]]; then
  echo "Загрузка официального исходного архива FFmpeg $VERSION..."
  /usr/bin/curl -fL --retry 3 -o "$ARCHIVE" "$URL"
fi

ACTUAL_SHA256=$(/usr/bin/shasum -a 256 "$ARCHIVE" | /usr/bin/awk '{print $1}')
if [[ "$ACTUAL_SHA256" != "$SHA256" ]]; then
  echo "Ошибка: контрольная сумма архива FFmpeg не совпала." >&2
  exit 1
fi

rm -rf "$SOURCE"
/usr/bin/tar -xf "$ARCHIVE" -C "$VENDOR"

cd "$VENDOR"
"$SOURCE/configure" \
  --prefix="$VENDOR/install" \
  --cc=/usr/bin/clang \
  --arch=arm64 \
  --target-os=darwin \
  --disable-debug \
  --disable-doc \
  --disable-programs \
  --enable-ffmpeg \
  --disable-network \
  --disable-autodetect \
  --disable-everything \
  --enable-avcodec \
  --enable-avformat \
  --enable-avfilter \
  --enable-swresample \
  --enable-protocol=file,pipe \
  --enable-demuxer=matroska,mov,mp3,wav,flac,ogg,aac \
  --enable-decoder=opus,vorbis,aac,alac,mp3,mp3float,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,flac \
  --enable-filter=aresample,aformat,pan \
  --enable-encoder=pcm_s16le \
  --enable-muxer=wav,pcm_s16le

/usr/bin/make -j4 ffmpeg
/bin/chmod +x "$OUTPUT"

LICENSE_TEXT=$("$OUTPUT" -L 2>&1)
if [[ "$LICENSE_TEXT" != *"GNU Lesser General Public"* ]]; then
  echo "Ошибка: собранный FFmpeg не сообщил лицензию LGPL." >&2
  exit 1
fi
VERSION_TEXT=$("$OUTPUT" -version 2>&1)
if [[ "$VERSION_TEXT" == *"--enable-gpl"* ]]; then
  echo "Ошибка: в конфигурации FFmpeg неожиданно включён GPL-код." >&2
  exit 1
fi

echo "$OUTPUT"
