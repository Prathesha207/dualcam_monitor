#!/usr/bin/env bash
# Install the backend and frontend correctly on a Linux development machine.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$BACKEND_DIR/../frontend" ]]; then
  FRONTEND_DIR="$(cd "$BACKEND_DIR/../frontend" && pwd)"
else
  FRONTEND_DIR="$(cd "$BACKEND_DIR/../vision-ai-frontend" && pwd)"
fi
VENV_DIR="$BACKEND_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "${1:-}" == "--clean" || "${1:-}" == "-c" ]]; then
  echo "Clean setup requested. Removing existing .venv..."
  rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR" || {
    echo "ERROR: Failed to create Python virtual environment."
    echo "On Ubuntu/Debian, install the required packages:"
    echo "  sudo apt update && sudo apt install -y python3-venv python3-pip python3-dev python3-tk zenity"
    exit 1
  }
fi

source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$BACKEND_DIR/requirements.txt"

# Check Luxonis OAK camera udev rules on Linux
if [[ ! -f /etc/udev/rules.d/80-movidius.rules ]]; then
  echo "--------------------------------------------------------"
  echo "NOTE: DepthAI OAK camera USB udev rules not detected."
  echo "If using USB OAK cameras without root permissions, run:"
  echo "  echo 'SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"03e7\", MODE=\"0666\"' | sudo tee /etc/udev/rules.d/80-movidius.rules"
  echo "  sudo udevadm control --reload-rules && sudo udevadm trigger"
  echo "--------------------------------------------------------"
fi

if [[ -f "$FRONTEND_DIR/package.json" ]]; then
  cd "$FRONTEND_DIR"
  npm install --include=optional
  npm run build
  cd "$BACKEND_DIR"
fi

if [[ -f "$BACKEND_DIR/test_smoke.py" ]]; then
  echo "Verifying backend camera service smoke test..."
  python "$BACKEND_DIR/test_smoke.py"
fi

echo "======================================================="
echo "Backend camera service setup completed successfully."
echo "======================================================="
