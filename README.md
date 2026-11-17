# Dual Cam Vision Monitor

A high-performance AI Vision Monitoring System with dual camera streaming, OAK (Luxonis DepthAI) hardware controls, real-time recording (AVI/MP4/MKV), and modern React/Vite dashboard interface.

---

## 📋 Prerequisites

Before setting up on a new PC, make sure you have:

| Tool | Recommended Version | Download Link |
|------|-------------------|---------------|
| **Git** | Latest | [git-scm.com](https://git-scm.com/downloads) |
| **Python** | 3.10, 3.11, or 3.12 (64-bit) | [python.org](https://www.python.org/downloads/) *(Check "Add Python to PATH" during install)* |
| **Node.js & npm** | Node v18+ or v20 LTS | [nodejs.org](https://nodejs.org/) |
| **Hardware** | Luxonis OAK Camera(s) | Connect via high-speed **USB 3.0** port (blue port or USB-C) |

---

## 🚀 Quick Setup (Automated 1-Click)

### Windows
1. Clone the repository:
   ```cmd
   git clone https://github.com/Prathesha207/dualcam_monitor.git
   cd dualcam_monitor
   ```
2. Double-click **`setup.bat`** (or run `setup.bat` in Command Prompt / PowerShell).
   - Automatically detects/installs Python & Node.js if missing.
   - Sets up Python virtual environment (`.venv`) and installs backend dependencies.
   - Installs frontend `node_modules` and builds assets.
   - Runs pre-flight camera validation.

3. Start the application:
   - Double-click **`run.bat`**.
   - Opens the frontend at: `http://localhost:5173`
   - Opens the backend API at: `http://localhost:8000` (docs at `http://localhost:8000/docs`)

---

### Linux / Ubuntu
1. Clone the repository:
   ```bash
   git clone https://github.com/Prathesha207/dualcam_monitor.git
   cd dualcam_monitor
   ```
2. Set up USB udev rules for DepthAI / OAK cameras (required on Linux for USB camera access):
   ```bash
   echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | sudo tee /etc/udev/rules.d/80-movidius.rules
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```
3. Run the setup script:
   ```bash
   chmod +x setup.sh run.sh
   ./setup.sh
   ```
4. Start the application:
   ```bash
   ./run.sh
   ```

---

## 🛠️ Manual Step-by-Step Setup

If you prefer to configure the backend and frontend separately:

### 1. Backend Setup (FastAPI & DepthAI)
```bash
# Navigate to backend
cd backend

# Create virtual environment
python -m venv .venv

# Activate virtual environment:
# On Windows (CMD / PowerShell):
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate

# Upgrade pip & install dependencies
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# (Optional) Copy environment config
copy .env.example .env    # On Linux: cp .env.example .env

# Run backend server
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. Frontend Setup (React, Vite, Tailwind)
```bash
# Open a new terminal and navigate to frontend
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

Visit **`http://localhost:5173`** in your browser.

---

## 📹 Simultaneous Color + 16-Bit Depth Recording

When recording is started with depth enabled, all synchronized tracks are stored directly in the **exact same session folder**:

| File | Codec / Format | Purpose | Description |
| :--- | :--- | :--- | :--- |
| **`clip001_01m00s.mp4`** *(or `.avi` / `.mkv`)* | H.264 / MJPEG / FFV1 | Normal Color Video | Full-resolution RGB video in the format you selected. |
| **`clip001_depth_raw_01m00s.mkv`** | FFV1 (`gray16le`) | **Scientific 16-Bit Depth** | **100% mathematically lossless**. Every pixel is the exact distance $Z$ in millimeters ($0$ to $65,535\text{ mm}$). Zero rounding or compression error. |
| **`clip001_depth_preview_01m00s.mp4`** *(or `.avi` / `.mkv`)* | Matching format with Turbo Colormap | **Visual Preview** | Colorized depth animation viewable directly in Windows Media Player, VLC, or web browser. |
| **`session.json`** | JSON | Manifest | Lists all clip filenames, frame counts, durations, and metadata. |

### How to Read Exact $Z$ Distance from Recorded Depth Video (Python):
```python
import av
import numpy as np

container = av.open("clip001_depth_raw_01m00s.mkv")
for frame in container.decode(video=0):
    depth_mm = frame.to_ndarray()  # dtype: uint16, shape: (H, W)
    
    # Distance in millimeters at pixel (x=320, y=240):
    z_mm = depth_mm[240, 320]
    z_meters = z_mm / 1000.0
    print(f"Object distance: {z_mm} mm ({z_meters:.3f} meters)")
```

---

## 📷 Camera Connection & Hardware Notes

1. **USB 3.0 Requirement**:
   - Luxonis OAK cameras transfer high-bandwidth raw/MJPEG video streams and depth maps. Always plug the cameras into **USB 3.0 / 3.1 / 3.2** ports (usually blue or marked with `SS`).
   - Avoid unpowered USB hubs.

2. **Windows Drivers**:
   - DepthAI relies on WinUSB drivers which are automatically configured by DepthAI when connected.

3. **Linux Permissions**:
   - On Linux, if DepthAI fails to find the device, ensure the udev rules mentioned above are configured.

---

## 📦 Building Standalone Desktop App (Electron)

To package as an installable desktop application:

- **Windows**: Double-click `build.bat` (outputs to `frontend/dist_app/`)
- **Linux**: Execute `./build_linux.sh`

---

## 🔍 Troubleshooting

- **Port 8000 or 5173 already in use**:
  `run.bat` automatically frees these ports. If running manually, terminate any existing python/node processes listening on those ports.
- **Camera not detected**:
  - Unplug and reconnect the camera to a different USB 3 port.
  - Verify device recognition using `python -c "import depthai; print(depthai.Device.getAllAvailableDevices())"`.
- **Python missing or version error**:
  - Python 3.10, 3.11, or 3.12 64-bit is required.
  - Make sure "Add Python to environment variables" was selected during Python installation.

