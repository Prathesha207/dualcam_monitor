#!/usr/bin/env bash
# Build Linux desktop artifacts from a native Ubuntu/Debian machine.
# Run this script from vision-ai-backend or repo root:
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "$SCRIPT_DIR/run.py" ]]; then
  BACKEND_DIR="$SCRIPT_DIR"
elif [[ -f "$PWD/vision-ai-backend/run.py" ]]; then
  BACKEND_DIR="$(cd "$PWD/vision-ai-backend" && pwd -P)"
elif [[ -f "$PWD/run.py" ]]; then
  BACKEND_DIR="$PWD"
else
  echo "Error: Cannot locate vision-ai-backend directory containing run.py."
  exit 1
fi

if [[ -d "$BACKEND_DIR/../frontend" ]]; then
  FRONTEND_DIR="$(cd "$BACKEND_DIR/../frontend" && pwd -P)"
elif [[ -d "$BACKEND_DIR/../vision-ai-frontend" ]]; then
  FRONTEND_DIR="$(cd "$BACKEND_DIR/../vision-ai-frontend" && pwd -P)"
elif [[ -d "$PWD/frontend" ]]; then
  FRONTEND_DIR="$(cd "$PWD/frontend" && pwd -P)"
elif [[ -d "$PWD/vision-ai-frontend" ]]; then
  FRONTEND_DIR="$(cd "$PWD/vision-ai-frontend" && pwd -P)"
else
  echo "Error: Cannot locate frontend directory."
  exit 1
fi

VENV_DIR="$BACKEND_DIR/.venv-linux-build"
MACHINE_ARCH="$(uname -m)"

case "$MACHINE_ARCH" in
  x86_64) ELECTRON_ARCH="x64" ;;
  aarch64|arm64) ELECTRON_ARCH="arm64" ;;
  *) echo "Unsupported Linux architecture: $MACHINE_ARCH"; exit 1 ;;
esac

if [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
  echo "vision-ai-frontend must be beside vision-ai-backend."
  exit 1
fi

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$BACKEND_DIR/requirements.txt"

cd "$BACKEND_DIR"
rm -rf "$BACKEND_DIR/build" "$BACKEND_DIR/dist"

pyinstaller --noconfirm --clean --onedir --name backend "$BACKEND_DIR/run.py" \
  --distpath "$BACKEND_DIR/dist" \
  --workpath "$BACKEND_DIR/build" \
  --specpath "$BACKEND_DIR" \
  --add-data "$BACKEND_DIR/alembic:alembic" \
  --exclude-module torch \
  --exclude-module torchvision \
  --exclude-module ultralytics \
  --exclude-module head_tail_analyzer \
  --collect-all app \
  --collect-all fastapi \
  --collect-all starlette \
  --collect-all uvicorn \
  --collect-all sqlalchemy \
  --collect-all cv2 \
  --collect-all depthai \
  --collect-all av \
  --collect-all imageio_ffmpeg

# Strip non-runtime development files directly in dist/backend
chmod +x "$BACKEND_DIR/dist/backend/backend"
find "$BACKEND_DIR/dist/backend" -name "*.a" -delete 2>/dev/null || true

cd "$FRONTEND_DIR"
npm ci --include=optional 2>/dev/null || npm install --include=optional
npm run "package:linux:$ELECTRON_ARCH"

echo
echo "Linux $ELECTRON_ARCH artifacts are in: $FRONTEND_DIR/dist_app"
