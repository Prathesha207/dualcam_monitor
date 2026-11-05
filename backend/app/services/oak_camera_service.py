# app/services/oak_camera_service.py
# Connect OAK camera
# Create DepthAI pipeline
# Capture frames
# Stream video
# Record video
# Control exposure/focus
# Disconnect camera
import asyncio
import os
import re
import threading
import time
from collections import deque
from queue import Queue, Empty

import cv2
import depthai as dai
import numpy as np
import logging
from app.services.realtime_log_service import realtime_log_service

logger = logging.getLogger("oak-camera")

# DepthAI XLink native layer is NOT thread-safe for device enumeration.
# Concurrent calls to dai.Device.getAllAvailableDevices() from multiple
# threads will corrupt internal state and crash the process with a segfault.
# This lock serialises every call that touches device discovery.
_depthai_device_enum_lock = threading.Lock()


def _extract_device_mxid(device_or_info) -> str:
    """Extract hardware MXID / Serial Number from dai.Device or dai.DeviceInfo."""
    if device_or_info is None:
        return ""
    if hasattr(device_or_info, "getMxId"):
        try:
            val = str(device_or_info.getMxId() or "").strip()
            if val:
                return val
        except Exception:
            pass
    if hasattr(device_or_info, "getXLinkDeviceDesc"):
        try:
            desc = device_or_info.getXLinkDeviceDesc()
            val = str(getattr(desc, "mxid", "") or "").strip()
            if val:
                return val
        except Exception:
            pass
    if hasattr(device_or_info, "getDeviceId"):
        try:
            val = str(device_or_info.getDeviceId() or "").strip()
            if val:
                return val
        except Exception:
            pass
    val = str(getattr(device_or_info, "deviceId", "") or "").strip()
    if val:
        return val
    return str(getattr(device_or_info, "name", "") or "").strip()


class OakCameraService:
    """Single OAK-D camera service for live streaming and recording.

    Pipeline (2 DAI output nodes):
      Camera -> VideoEncoder (MJPEG) -> _mjpeg_dai_queue
      Camera -> raw NV12             -> _raw_dai_queue

    Capture threads (3):
      _mjpeg_thread   : drains MJPEG DAI queue -> pushes JPEG into asyncio stream_queue
      _hires_thread   : drains raw NV12 DAI queue -> puts NV12 packets into _hires_packet_queue
      _convert_thread : pulls NV12 packets -> getCvFrame() -> stores _latest_bgr

    Streaming:
      HTTP StreamingResponse reads from stream_queue (asyncio.Queue)
      MJPEG thread pushes via run_coroutine_threadsafe (drop-oldest on full)
    """

    def __init__(self):
        # ---- Device ----
        self.device: dai.Device | None = None
        self.is_connected: bool = False
        self._connected_mxid: str | None = None
        self._last_device_scan_time: float = 0.0
        self._cached_device_detected: bool = False
        self._cached_devices_count: int = 0
        self._is_scanning_devices: bool = False
        self._last_connection_error: str | None = None

        # ---- Pipeline ----
        self._pipeline: dai.Pipeline | None = None
        self._is_running: bool = False
        self._pipeline_lock = threading.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._streaming_lock = asyncio.Lock()
        self._capture_lock = threading.Lock()
        self._camera_calibration_lock = threading.Lock()
        self._calibrating = False
        self._active_camera_id: int | None = None
        self._legacy_preset_migration = False

        # ---- DAI queues ----
        self._mjpeg_dai_queue = None
        self._raw_dai_queue = None
        self._control_queue = None

        # ---- Inter-thread queue (hires capture -> converter) ----
        self._hires_packet_queue: Queue = Queue(maxsize=16)

        # ---- Stream queue (MJPEG thread -> HTTP streaming endpoint) ----
        self._stream_queue: asyncio.Queue | None = None
        self._stream_subscribers: set[asyncio.Queue] = set()
        self._server_loop: asyncio.AbstractEventLoop | None = None
        self._is_streaming: bool = False

        # ---- Capture threads ----
        self._mjpeg_thread: threading.Thread | None = None
        self._hires_thread: threading.Thread | None = None
        self._convert_thread: threading.Thread | None = None

        self._mjpeg_stop = threading.Event()
        self._hires_stop = threading.Event()
        self._convert_stop = threading.Event()

        # ---- Latest BGR & JPEG frame caches ----
        self._latest_bgr: np.ndarray | None = None
        self._latest_jpeg: bytes | None = None
        self._latest_bgr_seq: int = 0
        self._latest_frame_data: tuple[np.ndarray, int, float] | None = None
        self._pipeline_width: int = 1920
        self._pipeline_height: int = 1080

        # ---- Camera settings ----
        self.control_mode: str = "auto"
        self.current_brightness: int = 0
        self.current_contrast: int = 50
        self.current_fps: float = 0.0
        self._configured_fps: int = 30
        self.current_exposure_us: int = 8000
        self._ae_limit_us = 10000
        self.current_gain: int = 400
        self.current_focus: int = 128
        self.focus_available: bool = True
        self.auto_exposure_enabled: bool = False
        self.auto_focus_enabled: bool = False
        self._latest_metadata: tuple[int, int, int | None] | None = None

        # ---- Recording ----
        self._active_recording = None

        # ---- Auto-calibration monitor ----
        self._monitor_last_calib_time: float = 0.0
        self._monitor_last_check: float = 0.0
        self._monitor_baseline_sharpness: float | None = None
        self._monitor_baseline_brightness: float | None = None
        self._monitor_bad_start_time: float | None = None

        self._load_saved_db_settings()

    def _load_saved_db_settings(self) -> None:
        """Load persisted camera settings from vision_ai.db into memory."""
        try:
            from app.core.database import SessionLocal
            from app.models.camera_model import Camera
            db = SessionLocal()
            try:
                cam = db.query(Camera).filter(Camera.id == self._active_camera_id).first() if self._active_camera_id else None
                cam = cam or db.query(Camera).order_by(Camera.id.desc()).first()
                if cam:
                    if cam.control_mode:
                        self.control_mode = cam.control_mode
                    if cam.exposure is not None:
                        exp_val = float(cam.exposure)
                        self.current_exposure_us = int(exp_val * 1000) if exp_val <= 1000 else int(exp_val)
                    if cam.gain is not None:
                        self.current_gain = int(cam.gain)
                    if cam.focus is not None and int(cam.focus) > 0:
                        self.current_focus = int(cam.focus)
                        self.focus_available = True
                    else:
                        self.current_focus = 128
                        self.focus_available = True
                    if cam.brightness is not None:
                        self.current_brightness = int(cam.brightness)
                    if cam.contrast is not None:
                        self.current_contrast = int(cam.contrast)
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"[INIT] Could not load DB camera settings: {e}")

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_recording(self) -> bool:
        return self._active_recording is not None

    # ==================== Device ====================

    async def connect(self, ip: str) -> bool:
        loop = asyncio.get_running_loop()
        self._last_connection_error = None
        self._configured_ip = str(ip or "").strip()
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                logger.info(f"[DEVICE] Connecting to {ip} (attempt {attempt + 1}/{max_attempts})")
                try:
                    claimed = set()
                    try:
                        if 'oak_camera_service' in globals() and hasattr(oak_camera_service, 'get_claimed_targets'):
                            claimed = oak_camera_service.get_claimed_targets(exclude_id=self._active_camera_id)
                        elif 'oak_camera_service' in globals() and hasattr(oak_camera_service, 'get_claimed_mxids'):
                            claimed = oak_camera_service.get_claimed_mxids(exclude_id=self._active_camera_id)
                    except Exception:
                        pass
                    device_info = await loop.run_in_executor(None, self._resolve_device_info, ip, claimed)
                except RuntimeError as resolve_err:
                    err_msg = str(resolve_err)
                    logger.warning(f"[DEVICE] Connection failed: {err_msg}")
                    self._last_connection_error = err_msg
                    self.is_connected = False
                    realtime_log_service.add_log(
                        "camera", "CAMERA",
                        err_msg,
                        "error"
                    )
                    return False
                logger.info(f"[DEVICE] Resolved connection target: {device_info}")
                self.device = await loop.run_in_executor(None, dai.Device, device_info)
                self.device.setLogLevel(dai.LogLevel.WARN)
                self.device.setLogOutputLevel(dai.LogLevel.WARN)
                self.is_connected = True

                # Hardware collision detection: ensure this physical camera is not already active as the other camera
                dev_mxid = _extract_device_mxid(self.device).lower()
                if dev_mxid:
                    self._connected_mxid = dev_mxid
                    if dev_mxid in claimed:
                        logger.warning(
                            f"[DEVICE] Camera {self._active_camera_id} connected to {ip}, "
                            f"but hardware serial '{dev_mxid}' is already claimed by another active camera!"
                        )
                        try:
                            await loop.run_in_executor(None, self.device.close)
                        except Exception:
                            pass
                        self.device = None
                        self.is_connected = False
                        self._connected_mxid = None
                        clean_msg = (
                            f"Camera hardware (Serial: {dev_mxid}) is already in use by another camera via USB or PoE. "
                            "Dual cameras must use separate physical hardware."
                        )
                        self._last_connection_error = clean_msg
                        realtime_log_service.add_log("camera", "CAMERA", clean_msg, "error")
                        return False

                try:
                    usb_speed = self.device.getUsbSpeed()
                    logger.info(f"[DEVICE] Connected link speed: {usb_speed}")
                    if usb_speed == dai.UsbSpeed.HIGH:
                        logger.warning(
                            "[DEVICE] ⚠️ Camera connected via USB 2.0 (HIGH speed: ~35-40 MB/s). "
                            "Uncompressed 1080p stream exceeds USB 2.0 bandwidth and will cause X_LINK_ERROR. "
                            "Please connect camera to a blue USB 3.0 port using a USB 3.0 SuperSpeed cable."
                        )
                        realtime_log_service.add_log(
                            "camera",
                            "WARN",
                            "OAK connected at USB 2.0 speed! Use a USB 3.0 port and cable for stability.",
                            "warning"
                        )
                except Exception as speed_err:
                    logger.debug(f"[DEVICE] Could not determine USB speed: {speed_err}")

                logger.info(f"[DEVICE] Connected to {ip}")
                realtime_log_service.add_log(
                    "camera",
                    "CAMERA",
                    f"Camera connected ({ip})",
                    "success"
                )
                self._last_connection_error = None
                return True
            except Exception as e:
                err_str = str(e)
                is_usb = not ip or str(ip).strip().lower() in {"usb", "auto"}
                if any(k in err_str.lower() for k in ["already used", "in use", "already_in_use", "busy", "occupied", "claimed"]):
                    if is_usb:
                        clean_msg = "USB device is already in use by another application/process. Make sure to close other software using the camera."
                    else:
                        clean_msg = f"Camera at {ip} is already in use by another application or camera."
                    self._last_connection_error = clean_msg
                    if attempt < max_attempts - 1:
                        logger.warning(f"[DEVICE] Device is reported in use, waiting 2.0s to retry (attempt {attempt + 1}/{max_attempts})...")
                        await asyncio.sleep(2.0)
                        continue
                    else:
                        logger.warning(f"[DEVICE] Connection failed after {max_attempts} attempts: {clean_msg}")
                        realtime_log_service.add_log("camera", "CAMERA", clean_msg, "error")
                        self.is_connected = False
                        return False
                elif any(k in err_str.lower() for k in ["not found", "no available", "x_link_device_not_found", "failed to find", "timeout", "cannot find", "searched"]):
                    if is_usb:
                        clean_msg = "No OAK camera detected over USB. Please check your USB 3.0 cable connection."
                    else:
                        clean_msg = f"No OAK camera found at {ip}. Please check that the IP address is correct and reachable."
                else:
                    clean_msg = f"Failed to connect to camera ({ip}): {err_str}"

                logger.error(f"[DEVICE] Connection failed: {clean_msg}")
                realtime_log_service.add_log("camera", "CAMERA", clean_msg, "error")
                self.is_connected = False
                self._last_connection_error = clean_msg
                return False
        self._last_connection_error = self._last_connection_error or "Failed after retries"
        return False

    async def disconnect(self) -> None:
        """Close physical DepthAI device handle."""
        if self.device is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.device.close)
            except Exception as e:
                logger.debug(f"[DISCONNECT] Device close error: {e}")
            finally:
                self.device = None
                self._connected_mxid = None
        self.is_connected = False
        self._last_connection_error = None

    @staticmethod
    def _resolve_device_info(identifier: str, exclude_mxids: set | None = None):
        """Resolve a database value to a current USB or network DeviceInfo without false fallback."""
        import ipaddress
        value = str(identifier or "").strip()
        excludes = exclude_mxids or set()

        # 1. USB Connection requested
        if not value or value.lower() in {"usb", "auto"}:
            with _depthai_device_enum_lock:
                devices = dai.Device.getAllAvailableDevices()
                if not devices:
                    raise RuntimeError("No OAK camera detected over USB. Please ensure the camera is plugged into a USB port.")

                unclaimed_usb = [
                    d for d in devices
                    if _extract_device_mxid(d).lower() not in excludes
                ]
                if unclaimed_usb:
                    return unclaimed_usb[0]

                if devices:
                    raise RuntimeError("USB camera is already in use by another camera. Dual cameras must use different hardware or IP addresses.")

                raise RuntimeError("No USB OAK camera found. Please connect an OAK camera via USB.")

        # 2. Check if the value is an IP address
        is_ip_candidate = ("." in value and any(c.isdigit() for c in value)) or value.replace(".", "").isdigit()
        if is_ip_candidate:
            # Validate IPv4 format strictly: 4 octets between 0 and 255
            try:
                ip_obj = ipaddress.IPv4Address(value)
                valid_ip = str(ip_obj)
            except Exception:
                raise RuntimeError(
                    f"Invalid IP address format: '{value}'. Expected a valid IPv4 address (e.g., 169.254.21.191)."
                )

            # Check if this IP is already occupied by the other camera
            if valid_ip.lower() in excludes:
                raise RuntimeError(
                    f"IP address '{valid_ip}' is already in use by another camera. Dual cameras must have different IP addresses."
                )

            # Check if an available device in getAllAvailableDevices matches this IP, name, or mxid
            with _depthai_device_enum_lock:
                devices = dai.Device.getAllAvailableDevices()
                for d in devices:
                    mxid = _extract_device_mxid(d).lower()
                    name = str(getattr(d, "name", "") or "").strip().lower()
                    desc_name = ""
                    try:
                        desc = d.getXLinkDeviceDesc()
                        desc_name = str(getattr(desc, "name", "") or "").strip().lower()
                    except Exception:
                        pass
                    if mxid and mxid in excludes and valid_ip.lower() in {name, desc_name, mxid}:
                        raise RuntimeError(
                            f"Camera at {value} (Serial: {mxid}) is already in use by another camera via USB or PoE. "
                            "Dual cameras must use separate physical hardware."
                        )
                    if valid_ip.lower() in {name, desc_name, mxid} and mxid not in excludes:
                        logger.info(f"[DEVICE] Found matching device in enumeration for '{valid_ip}': {d}")
                        return d

            # Target ONLY this IP address via dai.DeviceInfo
            # For RVC4 (OAK4) devices connected via USB networking (e.g. 172.22.x.x)
            # or Ethernet, we must explicitly set TCP/IP protocol and GATE state,
            # otherwise DepthAI's discovery layer cannot find the streaming endpoint.
            try:
                device_info = dai.DeviceInfo(valid_ip)
                # Try to set TCP/IP protocol and GATE state explicitly (required for RVC4 over USB network)
                try:
                    device_info.protocol = dai.XLinkProtocol.X_LINK_TCP_IP
                    device_info.state = dai.XLinkDeviceState.X_LINK_GATE
                    # X_LINK_RVC4 platform is required when state is GATE;
                    # without it DepthAI raises "Gate only supports RVC3 and RVC4 platforms"
                    try:
                        device_info.platform = dai.XLinkPlatform.X_LINK_RVC4
                    except AttributeError:
                        # Very old DepthAI builds may not expose X_LINK_RVC4; try RVC3 as fallback
                        try:
                            device_info.platform = dai.XLinkPlatform.X_LINK_RVC3
                        except AttributeError:
                            logger.warning("[DEVICE] XLinkPlatform.X_LINK_RVC4/RVC3 not available; Gate connection may fail")
                    logger.info(f"[DEVICE] IP connection configured with TCP/IP+GATE+RVC4 for: {valid_ip}")
                except AttributeError:
                    # Older DepthAI versions may not have these; fall back to plain DeviceInfo
                    logger.debug(f"[DEVICE] XLinkProtocol/XLinkDeviceState not available, using plain DeviceInfo for {valid_ip}")
                return device_info
            except Exception as e:
                raise RuntimeError(f"Failed to create connection for IP '{valid_ip}': {e}")

        # 3. Check if value is a specific MXID or device name
        with _depthai_device_enum_lock:
            devices = dai.Device.getAllAvailableDevices()
            if not devices:
                raise RuntimeError(f"No OAK device found matching '{value}' over USB or network.")

            for d in devices:
                mxid = _extract_device_mxid(d).lower()
                name = str(getattr(d, "name", "") or "").strip().lower()
                desc_name = ""
                try:
                    desc = d.getXLinkDeviceDesc()
                    desc_name = str(getattr(desc, "name", "") or "").strip().lower()
                except Exception:
                    pass
                if value.lower() in {mxid, name, desc_name}:
                    if mxid in excludes or name in excludes:
                        raise RuntimeError(f"Camera hardware ({value}) is already in use by another camera.")
                    return d

            raise RuntimeError(f"No OAK camera found matching '{value}'. Please verify the IP address or connection.")

    # ==================== Pipeline ====================
    # Camera -> Encoder (Raw Frames) -> JPEG Stream (Recording) 
    # Camera MJPEG(Stream) RAW NV12(Video File Recording)
    def _build_pipeline(self, pipeline: dai.Pipeline, config) -> bool:
        try:
            logger.info("[PIPELINE] Building...")

            resolution = config.resolution or "1920x1080"
            try:
                sep = "x" if "x" in resolution else "*"
                width, height = map(int, resolution.split(sep))
            except Exception:
                logger.warning("[PIPELINE] Bad resolution — fallback 1920x1080")
                width, height = 1920, 1080
            self._pipeline_width = width
            self._pipeline_height = height
            fps = max(5, min(60, int(config.fps or 30)))
            self._configured_fps = fps
            logger.info(f"[PIPELINE] {width}x{height} @ {fps}fps")

            control_mode = (config.control_mode or "auto").lower()
            self.control_mode = control_mode

            cam = None
            is_color_camera = False

            try:
                cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
                init_ctrl = cam.initialControl
            except Exception as cam_err:
                err_str = str(cam_err)
                logger.warning(f"[PIPELINE] dai.node.Camera build failed: {err_str}")
                try:
                    logger.info("[PIPELINE] Attempting dai.node.ColorCamera fallback...")
                    cam = pipeline.create(dai.node.ColorCamera)
                    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
                    if hasattr(dai.ColorCameraProperties, "SensorResolution"):
                        cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
                    cam.setFps(fps)
                    cam.setInterleaved(False)
                    cam.setVideoSize(width, height)
                    init_ctrl = cam.initialControl
                    is_color_camera = True
                    logger.info("[PIPELINE] ColorCamera node created successfully as fallback")
                except Exception as color_err:
                    logger.error(f"[PIPELINE] ColorCamera fallback also failed: {color_err}")
                    raise cam_err

            try:
                exposure = int(config.exposure if config.exposure is not None else 8)
                exposure = exposure * 1000 if exposure <= 1000 else exposure
                gain = max(100, min(1600, int(config.gain if config.gain is not None else 400)))
                focus = int(config.focus) if (config.focus is not None and int(config.focus) > 0) else 128
                if control_mode == "auto" and exposure == 16000 and gain == 400 and focus == 120:
                    exposure, focus = 8000, 128
                    self._legacy_preset_migration = True
            except (TypeError, ValueError):
                logger.warning("[PIPELINE] Invalid saved camera values; using 8ms/ISO400 preset")
                exposure, gain, focus = 8000, 400, 128

            self.current_exposure_us = max(100, min(33000, exposure))
            self.current_gain = gain
            self.current_focus = focus
            self.focus_available = focus is not None
            self.current_brightness = int(config.brightness or 0)
            self.current_contrast = int(config.contrast if config.contrast is not None else 50)
            self.auto_exposure_enabled = self.auto_focus_enabled = False
            init_ctrl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.OFF)
            if focus is not None:
                init_ctrl.setManualFocus(focus)
            init_ctrl.setManualExposure(self.current_exposure_us, gain)
            hw_b = max(-10, min(10, int(round(self.current_brightness / 5.0))))
            hw_c = max(-10, min(10, int(round((self.current_contrast - 50) / 5.0))))
            init_ctrl.setBrightness(hw_b)
            init_ctrl.setContrast(hw_c)
            logger.info(f"[PIPELINE] {control_mode} fixed preset: exp={self.current_exposure_us}us, gain={gain}, focus={focus}")

            is_usb2 = False
            if self.device is not None:
                try:
                    if self.device.getUsbSpeed() == dai.UsbSpeed.HIGH:
                        is_usb2 = True
                        logger.warning(
                            "[PIPELINE] ⚠️ Detected USB 2.0 connection. "
                            "Uncompressed 1080p @ 30fps requires ~93 MB/s which exceeds USB 2.0 bandwidth (~35 MB/s). "
                            "Throttling raw frame output rate to 10 FPS to prevent XLink communication buffer overflows. "
                            "Please connect camera to a blue USB 3.0 port with a SuperSpeed cable for full 30 FPS."
                        )
                except Exception:
                    pass

            raw_fps = min(fps, 10) if is_usb2 else fps

            encoder = pipeline.create(dai.node.VideoEncoder)
            encoder.setDefaultProfilePreset(fps, dai.VideoEncoderProperties.Profile.MJPEG)
            encoder.setQuality(95)

            if not is_color_camera:
                # --- Node 1: MJPEG encoder → stream preview ---
                mjpeg_out = cam.requestOutput(
                    (width, height), type=dai.ImgFrame.Type.NV12, fps=fps
                )
                mjpeg_out.link(encoder.input)
                self._mjpeg_dai_queue = encoder.bitstream.createOutputQueue(maxSize=4, blocking=False)
                logger.info("[PIPELINE] Node 1: MJPEG encoder ready")

                # --- Node 2: Raw NV12 → recording ---
                raw_out = cam.requestOutput(
                    (width, height), type=dai.ImgFrame.Type.NV12, fps=raw_fps
                )
                self._raw_dai_queue = raw_out.createOutputQueue(maxSize=2, blocking=False)
                logger.info(f"[PIPELINE] Node 2: Raw NV12 ready (fps={raw_fps})")
            else:
                cam.video.link(encoder.input)
                self._mjpeg_dai_queue = encoder.bitstream.createOutputQueue(maxSize=4, blocking=False)
                self._raw_dai_queue = cam.video.createOutputQueue(maxSize=2, blocking=False)
                logger.info("[PIPELINE] ColorCamera outputs wired successfully")

            # --- Camera control input ---
            self._control_queue = cam.inputControl.createInputQueue(maxSize=4, blocking=False)

            logger.info("[PIPELINE] Build success")
            return True

        except Exception as e:
            logger.error(f"[PIPELINE] Build failed: {e}", exc_info=True)
            return False

    def _cleanup_pipeline(self) -> None:
        with self._pipeline_lock:
            if self._pipeline is None:
                return
            logger.info("[PIPELINE] Stopping...")
            try:
                self._pipeline.stop()
                self._pipeline.wait()
            except Exception as e:
                logger.error(f"[PIPELINE] Stop error: {e}")
            finally:
                self._pipeline = None
                self._is_running = False
                self._mjpeg_dai_queue = None
                self._raw_dai_queue = None
                self._control_queue = None
                self._latest_jpeg = None
                self._latest_bgr = None
            logger.info("[PIPELINE] Cleaned up")

    def _on_device_lost(self, reason: str = "Device disconnected") -> None:
        """Central teardown when DepthAI device disconnects, XLink crashes, or queues close."""
        with self._pipeline_lock:
            if not self._is_running and not self.is_connected:
                return
            logger.warning(f"[DEVICE] Teardown triggered: {reason}")
            self._is_running = False
            self.is_connected = False
            self._is_streaming = False

            self._mjpeg_stop.set()
            self._hires_stop.set()
            self._convert_stop.set()

            self._mjpeg_dai_queue = None
            self._raw_dai_queue = None
            self._control_queue = None
            self._pipeline = None
            self._latest_jpeg = None
            self._latest_bgr = None

            loop = self._server_loop
            for q in list(self._stream_subscribers):
                if loop is not None and not loop.is_closed():
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, None)
                    except Exception:
                        pass
                else:
                    try:
                        q.put_nowait(None)
                    except Exception:
                        pass
            self._stream_subscribers.clear()
            self._stream_queue = None

            if self.device is not None:
                try:
                    self.device.close()
                except Exception:
                    pass
                self.device = None

            realtime_log_service.add_log(
                "camera",
                "CAMERA",
                f"Camera device disconnected: {reason}",
                "error"
            )

    # ==================== Capture Threads ====================

    def _start_capture_threads(self) -> bool:
        with self._capture_lock:
            if not self._is_running or not self.is_connected or self._mjpeg_dai_queue is None:
                logger.warning("[CAPTURE] Cannot start — pipeline or device queue not running")
                return False

            mjpeg_alive = self._mjpeg_thread and self._mjpeg_thread.is_alive()
            hires_alive = self._hires_thread and self._hires_thread.is_alive()
            convert_alive = self._convert_thread and self._convert_thread.is_alive()

            if not mjpeg_alive:
                self._mjpeg_stop.clear()
                self._mjpeg_thread = threading.Thread(
                    target=self._mjpeg_loop, name="oak-mjpeg", daemon=True
                )
                self._mjpeg_thread.start()
                logger.info("[CAPTURE] MJPEG thread started")

            if not hires_alive:
                self._hires_stop.clear()
                self._hires_thread = threading.Thread(
                    target=self._hires_loop, name="oak-hires", daemon=True
                )
                self._hires_thread.start()
                logger.info("[CAPTURE] Hi-res thread started")

            if not convert_alive:
                self._convert_stop.clear()
                self._convert_thread = threading.Thread(
                    target=self._convert_loop, name="oak-convert", daemon=True
                )
                self._convert_thread.start()
                logger.info("[CAPTURE] Converter thread started")

            return True

    def _stop_capture_threads(self) -> None:
        with self._capture_lock:
            logger.info("[CAPTURE] Stopping threads...")

            self._mjpeg_stop.set()
            self._hires_stop.set()
            self._convert_stop.set()

            if self._convert_thread and self._convert_thread.is_alive():
                self._convert_thread.join(timeout=3.0)
            self._convert_thread = None

            if self._mjpeg_thread and self._mjpeg_thread.is_alive():
                self._mjpeg_thread.join(timeout=2.0)
            self._mjpeg_thread = None

            if self._hires_thread and self._hires_thread.is_alive():
                self._hires_thread.join(timeout=2.0)
            self._hires_thread = None

            self._latest_bgr = None
            self._latest_bgr_seq = -1
            self._latest_frame_data = None
            self._latest_jpeg = None
            self._drain_hires_packet_queue()

            logger.info("[CAPTURE] Threads stopped")

    def _drain_hires_packet_queue(self) -> None:
        drained = 0
        while not self._hires_packet_queue.empty():
            try:
                self._hires_packet_queue.get_nowait()
                drained += 1
            except Empty:
                break
        if drained:
            logger.info(f"[CAPTURE] Drained {drained} stale hi-res packets")

    # ---- Thread 1: MJPEG consumer ----

    def _mjpeg_loop(self) -> None:
        """Drains MJPEG DAI queue and pushes JPEG bytes into the asyncio stream_queue."""
        logger.info("[MJPEG] Thread running")
        frames = 0
        frames_pushed = 0
        frames_dropped = 0
        last_log = time.time()
        last_frame_ts = time.time()

        try:
            while not self._mjpeg_stop.is_set():
                if self._mjpeg_dai_queue is None:
                    time.sleep(0.001)
                    continue

                pkt = self._mjpeg_dai_queue.tryGet()
                if pkt is None:
                    has_subscribers = bool(self._stream_subscribers) or (self._stream_queue is not None)
                    if (
                        self._is_running
                        and self.is_connected
                        and self._is_streaming
                        and has_subscribers
                        and time.time() - last_frame_ts > 15.0
                    ):
                        logger.error("[MJPEG] Watchdog: No frames from camera for 15.0s during active streaming — device wedged")
                        self._on_device_lost("No frames from camera (watchdog timeout)")
                        break
                    time.sleep(0.001)
                    continue

                last_frame_ts = time.time()
                try:
                    jpeg = pkt.getData().tobytes()
                except Exception as e:
                    logger.warning(f"[MJPEG] Frame extraction failed: {e}")
                    continue

                self._latest_jpeg = jpeg
                frames += 1

                loop = self._server_loop
                if loop is not None and not loop.is_closed():
                    loop.call_soon_threadsafe(self._push_sync, jpeg)
                    frames_pushed += 1
                else:
                    self._push_sync(jpeg)
                    frames_pushed += 1

                now = time.time()
                if now - last_log >= 2.0:
                    elapsed = now - last_log
                    mjpeg_fps = frames / elapsed
                    logger.info(
                        f"[MJPEG] FPS: {mjpeg_fps:.1f} | "
                        f"subscribers: {len(self._stream_subscribers)} | "
                        f"pushed: {frames_pushed} | dropped: {frames_dropped}"
                    )
                    frames = 0
                    frames_pushed = 0
                    frames_dropped = 0
                    last_log = now

        except Exception as e:
            if not self._mjpeg_stop.is_set():
                err_msg = str(e)
                if "closed" in err_msg.lower() or "xlink" in err_msg.lower():
                    logger.warning(f"[MJPEG] Device connection lost: {err_msg}")
                else:
                    logger.error(f"[MJPEG] Thread error: {e}", exc_info=True)
                self._on_device_lost(f"MJPEG queue closed: {err_msg}")
        finally:
            logger.info("[MJPEG] Thread ended")

    # ---- Thread 2: Hi-res capture ----

    def _hires_loop(self) -> None:
        """Drains raw NV12 DAI queue and queues packets for the converter thread."""
        logger.info("[HIRES] Thread running")

        try:
            while not self._hires_stop.is_set():
                if self._raw_dai_queue is None:
                    time.sleep(0.001)
                    continue

                pkt = self._raw_dai_queue.tryGet()
                if pkt is None:
                    time.sleep(0.005)
                    continue

                try:
                    exp = int(pkt.getExposureTime().total_seconds() * 1_000_000)
                    iso = int(pkt.getSensitivity())
                    lens = int(pkt.getLensPosition())
                    self._latest_metadata = (exp, iso, lens if 0 <= lens <= 255 else None)
                except Exception:
                    pass

                while not self._hires_packet_queue.empty():
                    try:
                        self._hires_packet_queue.get_nowait()
                    except Exception:
                        break
                try:
                    self._hires_packet_queue.put_nowait(pkt)
                except Exception:
                    pass

        except Exception as e:
            if not self._hires_stop.is_set():
                err_msg = str(e)
                if "closed" in err_msg.lower() or "xlink" in err_msg.lower():
                    logger.warning(f"[HIRES] Device connection lost: {err_msg}")
                else:
                    logger.error(f"[HIRES] Thread error: {e}", exc_info=True)
                self._on_device_lost(f"Hi-res queue closed: {err_msg}")
        finally:
            logger.info("[HIRES] Thread ended")

    # ---- Thread 3: Converter ----

    def _convert_loop(self) -> None:
        """Pulls NV12 packets, converts to BGR (getCvFrame), stores latest for recording."""
        logger.info("[CONVERT] Thread running")
        frames = 0
        record_frames = 0
        last_log = time.time()
        _first_frame_logged = False

        try:
            while not self._convert_stop.is_set() or not self._hires_packet_queue.empty():
                pkt = None
                while not self._hires_packet_queue.empty():
                    try:
                        pkt = self._hires_packet_queue.get_nowait()
                    except Empty:
                        break
                if pkt is None:
                    try:
                        pkt = self._hires_packet_queue.get(timeout=0.05)
                    except Empty:
                        continue

                try:
                    raw_bgr = pkt.getCvFrame()
                except Exception as e:
                    logger.warning(f"[CONVERT] getCvFrame failed: {e}")
                    continue

                seq_num = self._latest_bgr_seq + 1
                ts_sec = time.time()
                try:
                    seq_num = pkt.getSequenceNum()
                except Exception:
                    pass

                if not _first_frame_logged:
                    logger.info(f"[CONVERT] First frame received — shape={raw_bgr.shape} | ae_limit_us={self._ae_limit_us} | configured_fps={self._configured_fps}")
                    _first_frame_logged = True

                display_bgr = raw_bgr

                if self.control_mode == "auto" and not self._calibrating:
                    self._run_monitor(display_bgr)
                elif self.control_mode == "manual":
                    self._monitor_baseline_sharpness = None

                self._latest_bgr = display_bgr
                self._latest_bgr_seq = seq_num
                self._latest_frame_data = (display_bgr, seq_num, ts_sec)

                if self._active_recording is not None:
                    self._active_recording.add_frame(display_bgr)
                    record_frames += 1

                frames += 1
                now = time.time()
                if now - last_log >= 2.0:
                    elapsed = now - last_log
                    self.current_fps = frames / elapsed
                    expected = self._configured_fps
                    fps_status = "OK" if self.current_fps >= expected * 0.8 else f"LOW (expected ~{expected})"
                    logger.info(
                        f"[CONVERT] FPS: {self.current_fps:.1f} [{fps_status}] | "
                        f"recording: {self._active_recording is not None} | "
                        f"record_frames_fed: {record_frames} | "
                        f"ae_limit_us: {self._ae_limit_us}"
                    )
                    frames = 0
                    record_frames = 0
                    last_log = now

        except Exception as e:
            logger.error(f"[CONVERT] Thread error: {e}", exc_info=True)
        finally:
            logger.info("[CONVERT] Thread ended")

    # ==================== Stream Queue ====================

    def _push_sync(self, jpeg: bytes) -> None:
        """Runs on the asyncio event loop thread — drop-oldest push into all client queues."""
        for q in list(self._stream_subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(jpeg)
            except asyncio.QueueFull:
                pass
        if self._stream_queue is not None and self._stream_queue not in self._stream_subscribers:
            if self._stream_queue.full():
                try:
                    self._stream_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                self._stream_queue.put_nowait(jpeg)
            except asyncio.QueueFull:
                pass

    def subscribe_stream(self) -> asyncio.Queue:
        try:
            self._server_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        q: asyncio.Queue = asyncio.Queue(maxsize=4)
        self._stream_subscribers.add(q)
        self._stream_queue = q
        logger.info(f"[STREAM] Client subscribed — active subscribers: {len(self._stream_subscribers)}")
        return q

    def unsubscribe_stream(self, q: asyncio.Queue | None = None) -> None:
        if q is not None:
            self._stream_subscribers.discard(q)
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
        else:
            for sub in list(self._stream_subscribers):
                while not sub.empty():
                    try:
                        sub.get_nowait()
                    except asyncio.QueueEmpty:
                        break
            self._stream_subscribers.clear()

        if self._stream_subscribers:
            self._stream_queue = next(iter(self._stream_subscribers))
        else:
            self._stream_queue = None
        logger.info(f"[STREAM] Client unsubscribed — remaining subscribers: {len(self._stream_subscribers)}")

    def _open_stream_queue(self) -> asyncio.Queue:
        return self.subscribe_stream()

    def _close_stream_queue(self, q: asyncio.Queue | None = None) -> None:
        self.unsubscribe_stream(q)

    async def get_stream_frame(self, timeout: float = 1.0) -> bytes | None:
        if self._latest_jpeg is not None:
            return self._latest_jpeg
        if self._stream_queue is not None:
            try:
                return await asyncio.wait_for(self._stream_queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        if self._latest_bgr is not None:
            try:
                frame_copy = self._latest_bgr.copy()
                loop = asyncio.get_running_loop()
                def _encode():
                    ret, buf = cv2.imencode(".jpg", frame_copy, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    return buf.tobytes() if ret else None
                return await loop.run_in_executor(None, _encode)
            except Exception:
                pass
        return None

    # ==================== Frame Access ====================

    def get_bgr_frame(self) -> np.ndarray | None:
        """Latest BGR frame for snapshot / recording."""
        frame = self._latest_bgr
        return frame.copy() if frame is not None else None

    # ==================== Auto-calibration Monitor ====================

    def _safe_calibrate(self) -> None:
        try:
            logger.info("[MONITOR] Starting automatic calibration")
            self.calibrate_auto_controls()
        except Exception as e:
            logger.error(f"[MONITOR] Auto-calibration failed: {e}")

    def _run_monitor(self, frame: np.ndarray) -> None:
        now = time.time()
        if now - self._monitor_last_calib_time < 5.0 or now - self._monitor_last_check < 0.5:
            return
        
        self._monitor_last_check = now

        h, w = frame.shape[:2]
        crop = frame[h//4:3*h//4, w//4:3*w//4]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        sharpness = cv2.Laplacian(gray, cv2.CV_32F).var()
        brightness = gray.mean()

        if self._monitor_baseline_sharpness is None:
            self._monitor_baseline_sharpness = sharpness
            self._monitor_baseline_brightness = brightness
            self._monitor_bad_start_time = None
            logger.info(f"[MONITOR] Baseline set - Sharpness: {sharpness:.1f}, Brightness: {brightness:.1f}")
            return

        sharpness_drop = sharpness < (self._monitor_baseline_sharpness * 0.5)
        brightness_shift = abs(brightness - self._monitor_baseline_brightness) > 30.0

        if sharpness_drop or brightness_shift:
            if self._monitor_bad_start_time is None:
                self._monitor_bad_start_time = now
            elif now - self._monitor_bad_start_time > 1.0:
                logger.info(f"[MONITOR] Triggering auto-calibration. Sharpness: {sharpness:.1f} (baseline: {self._monitor_baseline_sharpness:.1f}), Brightness: {brightness:.1f} (baseline: {self._monitor_baseline_brightness:.1f})")
                self._monitor_last_calib_time = now
                self._monitor_baseline_sharpness = None
                self._monitor_bad_start_time = None
                threading.Thread(target=self._safe_calibrate, name="oak-monitor-calib", daemon=True).start()
        else:
            self._monitor_bad_start_time = None

    # ==================== Camera Controls ====================

    def reset_controls(self) -> dict:
        """Reapply the saved default preset from database."""
        self._load_saved_db_settings()
        self.auto_exposure_enabled = self.auto_focus_enabled = False
        self._monitor_baseline_sharpness = None
        ctrl = dai.CameraControl()
        ctrl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.OFF)
        if self.current_focus is not None:
            ctrl.setManualFocus(self.current_focus)
        ctrl.setManualExposure(self.current_exposure_us, self.current_gain)
        hw_b = max(-10, min(10, int(round(self.current_brightness / 5.0))))
        hw_c = max(-10, min(10, int(round((self.current_contrast - 50) / 5.0))))
        ctrl.setBrightness(hw_b)
        ctrl.setContrast(hw_c)
        try:
            if self._control_queue is not None and self._is_running and self.is_connected:
                self._control_queue.send(ctrl)
        except Exception as e:
            logger.warning(f"[CONTROL] Preset apply failed: {e}")
            return {"status": "error", "message": str(e)}
        return {"status": "ok", **self._camera_settings()}

    def update_controls(
        self, exposure: int | None = None, gain: int | None = None,
        focus: int | None = None, brightness: int | None = None,
        contrast: int | None = None, auto_focus: bool | None = None,
        auto_exposure: bool | None = None, control_mode: str | None = None,
        reset: bool | None = None,
    ) -> None:
        """Apply fixed user or saved preset values. Legacy AE/AF flags are ignored."""
        if reset:
            self.reset_controls()
            return
        requested_mode = (control_mode or "").lower()
        if requested_mode in {"auto", "manual"}:
            self.control_mode = requested_mode
        if requested_mode == "manual" or (not requested_mode and any(v is not None for v in (exposure, gain, focus))):
            self.control_mode = "manual"
        if brightness is not None:
            self.current_brightness = max(-50, min(50, int(brightness)))
        if contrast is not None:
            self.current_contrast = max(0, min(100, int(contrast)))
        if gain is not None:
            self.current_gain = max(100, min(1600, int(gain)))
        if focus is not None:
            self.current_focus = max(0, min(255, int(focus)))
            self.focus_available = True
        if exposure is not None:
            value = int(exposure)
            exp_us = value * 1000 if value <= 1000 else value
            max_us = max(1000, int(1_000_000 / max(self._configured_fps, 1)))
            self.current_exposure_us = max(100, min(max_us, exp_us))
        self.auto_exposure_enabled = self.auto_focus_enabled = False
        self._monitor_baseline_sharpness = None
        if not self._is_running or not self.is_connected or self._control_queue is None:
            return
        ctrl = dai.CameraControl()
        if self.control_mode == "auto":
            self.auto_exposure_enabled = self.auto_focus_enabled = True
            ctrl.setAutoExposureEnable()
            ctrl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.CONTINUOUS_VIDEO)
        else:
            self.auto_exposure_enabled = self.auto_focus_enabled = False
            ctrl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.OFF)
            if self.current_focus is not None:
                ctrl.setManualFocus(self.current_focus)
            ctrl.setManualExposure(self.current_exposure_us, self.current_gain)
        ctrl.setBrightness(max(-10, min(10, int(round(self.current_brightness / 5.0)))))
        ctrl.setContrast(max(-10, min(10, int(round((self.current_contrast - 50) / 5.0)))))
        try:
            self._control_queue.send(ctrl)
        except Exception as ctrl_err:
            logger.warning(f"[CONTROL] Control queue send failed: {ctrl_err}")
        if self._active_recording is not None:
            self._active_recording.add_settings_event(self._recording_settings_snapshot())

    def _camera_settings(self) -> dict:
        return {
            "control_mode": self.control_mode,
            "exposure": round(self.current_exposure_us / 1000, 3),
            "gain": self.current_gain,
            "focus": self.current_focus,
            "focus_available": self.focus_available,
            "brightness": self.current_brightness,
            "contrast": self.current_contrast,
            "auto_exposure": False,
            "auto_focus": False,
            "calibrating": self._calibrating,
        }

    def calibrate_auto_controls(self) -> dict:
        """Use a short AE/one-shot AF phase, then freeze the measured metadata."""
        if not self._is_running or not self.is_connected or self._control_queue is None:
            raise RuntimeError("Start the OAK camera before calibrating")
        if self._active_recording is not None:
            raise RuntimeError("Stop recording before calibrating")
        if not self._camera_calibration_lock.acquire(blocking=False):
            raise RuntimeError("Camera calibration is already running")
        
        self._calibrating = True
        prev_exposure = self.current_exposure_us
        prev_gain = self.current_gain
        prev_focus = self.current_focus
        
        try:
            settle = dai.CameraControl()
            settle.setAutoExposureEnable()
            settle.setAutoExposureLimit(10000)
            settle.setAutoFocusMode(dai.CameraControl.AutoFocusMode.OFF)
            if self.current_focus is not None:
                settle.setManualFocus(self.current_focus)
            self._control_queue.send(settle)
            
            time.sleep(1.5)
            
            latest = self._latest_metadata
            if latest is None:
                raise RuntimeError("No exposure and gain metadata arrived during calibration")
            exp_us, iso, lens = latest
            
            lock = dai.CameraControl()
            lock.setAutoFocusMode(dai.CameraControl.AutoFocusMode.OFF)
            if self.current_focus is not None:
                lock.setManualFocus(self.current_focus)
            lock.setManualExposure(exp_us, iso)
            self._control_queue.send(lock)
            
            self.current_exposure_us = exp_us
            self.current_gain = max(100, min(1600, iso))
            self.control_mode = "auto"
            self.current_brightness, self.current_contrast = 0, 50
            self.auto_exposure_enabled = self.auto_focus_enabled = False
            self._save_calibrated_preset()
            return {"status": "ok", **self._camera_settings()}
        except Exception as e:
            logger.error(f"[CALIBRATION] Calibration failed: {e}")
            try:
                restore = dai.CameraControl()
                restore.setAutoFocusMode(dai.CameraControl.AutoFocusMode.OFF)
                if prev_focus is not None:
                    restore.setManualFocus(prev_focus)
                restore.setManualExposure(prev_exposure, prev_gain)
                self._control_queue.send(restore)
            except Exception as restore_error:
                logger.error(f"[CALIBRATION] Failed to restore fixed controls after calibration error: {restore_error}")
            raise RuntimeError(str(e)) from e
        finally:
            self._calibrating = False
            self._camera_calibration_lock.release()

    def _save_calibrated_preset(self) -> None:
        from app.core.database import SessionLocal
        from app.models.camera_model import Camera
        db = SessionLocal()
        try:
            camera = db.query(Camera).filter(Camera.id == self._active_camera_id).first() if self._active_camera_id else None
            camera = camera or db.query(Camera).first()
            if camera:
                camera.control_mode = "auto"
                camera.exposure = round(self.current_exposure_us / 1000, 3)
                camera.gain, camera.focus = self.current_gain, self.current_focus
                camera.brightness, camera.contrast = self.current_brightness, self.current_contrast
                camera.auto_exposure = camera.auto_focus = False
                db.commit()
                logger.info(f"[CALIBRATION] Saved calibrated preset to DB: exp={camera.exposure}ms, gain={camera.gain}, focus={camera.focus}")
        finally:
            db.close()

    def save_current_controls_to_db(self, control_mode: str = "manual") -> dict:
        """Persist current runtime controls directly to vision_ai.db."""
        from app.core.database import SessionLocal
        from app.models.camera_model import Camera
        db = SessionLocal()
        try:
            camera = db.query(Camera).filter(Camera.id == self._active_camera_id).first() if self._active_camera_id else None
            camera = camera or db.query(Camera).first()
            if camera:
                camera.control_mode = control_mode
                camera.exposure = round(self.current_exposure_us / 1000, 3)
                camera.gain = float(self.current_gain)
                camera.focus = self.current_focus if (self.current_focus is not None and self.current_focus > 0) else (camera.focus or 128)
                camera.brightness = self.current_brightness
                camera.contrast = self.current_contrast
                camera.auto_exposure = False
                camera.auto_focus = False
                db.commit()
                logger.info(
                    f"[CONTROL] Saved {control_mode} controls to DB: "
                    f"exp={camera.exposure}ms, gain={camera.gain}, focus={camera.focus}, "
                    f"brightness={camera.brightness}, contrast={camera.contrast}"
                )
                return {"status": "ok", "message": "Settings saved to database", **self._camera_settings()}
            return {"status": "error", "message": "No camera found in database"}
        except Exception as e:
            logger.error(f"[CONTROL] Failed to save controls to DB: {e}")
            raise
        finally:
            db.close()

    def get_hardware_calibration(self, width: int | None = None, height: int | None = None) -> dict:
        """Read 100% genuine hardware calibration and intrinsics from OAK-D camera EEPROM."""
        calib = None
        device_mxid = None

        if self.device is not None and self.is_connected:
            try:
                calib = self.device.readCalibration()
                device_mxid = self.device.getMxId()
            except Exception as e:
                logger.warning(f"[CALIBRATION] Failed reading calibration from active device: {e}")

        if calib is None:
            with _depthai_device_enum_lock:
                devices = dai.Device.getAllAvailableDevices()
                if not devices:
                    return {
                        "status": "error",
                        "message": "No OAK-D camera detected via USB. Please connect the camera."
                    }
                device_info = devices[0]
                device_mxid = device_info.getMxId()
                try:
                    with dai.Device(device_info) as dev:
                        calib = dev.readCalibration()
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Failed to connect to OAK-D device ({device_mxid}): {e}"
                    }

        if not calib.hasCalibrationData():
            return {
                "status": "error",
                "message": f"Connected device ({device_mxid}) has no factory calibration data in EEPROM."
            }

        socket = dai.CameraBoardSocket.CAM_A

        try:
            raw_matrix, native_calib_w, native_calib_h = calib.getDefaultIntrinsics(socket)
        except Exception:
            raw_matrix = calib.getCameraIntrinsics(socket)
            native_calib_w = 0
            native_calib_h = 0

        try:
            source_w = calib.getSourceWidth(socket)
            source_h = calib.getSourceHeight(socket)
        except Exception:
            source_w, source_h = native_calib_w, native_calib_h

        if width is not None and height is not None:
            actual_w, actual_h = int(width), int(height)
        elif getattr(self, "_pipeline_width", None) and getattr(self, "_pipeline_height", None):
            actual_w, actual_h = int(self._pipeline_width), int(self._pipeline_height)
        else:
            actual_w = native_calib_w or source_w
            actual_h = native_calib_h or source_h

        try:
            k = np.array(calib.getCameraIntrinsics(socket, actual_w, actual_h))
        except Exception:
            k = np.array(raw_matrix)

        try:
            dist_coeffs = [float(c) for c in calib.getDistortionCoefficients(socket)]
        except Exception:
            dist_coeffs = []

        try:
            dist_model = str(calib.getDistortionModel(socket))
        except Exception:
            dist_model = None

        try:
            baseline_cm = calib.getBaselineDistance(dai.CameraBoardSocket.CAM_B, dai.CameraBoardSocket.CAM_C)
            baseline_mm = float(baseline_cm * 10.0)
        except Exception:
            baseline_mm = None

        try:
            fov_deg = float(calib.getFov(socket))
        except Exception:
            fov_deg = None

        fx = float(k[0, 0])
        fy = float(k[1, 1])
        cx = float(k[0, 2])
        cy = float(k[1, 2])

        yaml_lines = [
            "CAMERA_MATRIX:",
            f"  - [{k[0, 0]:.6f}, {k[0, 1]:.6f}, {k[0, 2]:.6f}]",
            f"  - [{k[1, 0]:.6f}, {k[1, 1]:.6f}, {k[1, 2]:.6f}]",
            f"  - [{k[2, 0]:.6f}, {k[2, 1]:.6f}, {k[2, 2]:.6f}]",
            f"CALIBRATION_WIDTH: {actual_w}",
            f"CALIBRATION_HEIGHT: {actual_h}",
        ]
        if dist_coeffs:
            formatted_coeffs = ", ".join(f"{c:.6f}" for c in dist_coeffs)
            yaml_lines.append(f"DISTORTION_COEFFICIENTS: [{formatted_coeffs}]")
        yaml_string = "\n".join(yaml_lines)

        return {
            "status": "ok",
            "device_mxid": device_mxid,
            "calibration_width": actual_w,
            "calibration_height": actual_h,
            "sensor_source_width": source_w,
            "sensor_source_height": source_h,
            "camera_matrix": k.tolist(),
            "fx": fx,
            "fy": fy,
            "cx": cx,
            "cy": cy,
            "distortion_coefficients": dist_coeffs,
            "distortion_model": dist_model,
            "baseline_distance_mm": baseline_mm,
            "fov_degrees": fov_deg,
            "yaml_string": yaml_string,
        }

    # ==================== Recording ====================

    def _resolve_recording_path(self) -> str | None:
        try:
            from app.services.recording_service import _resolve_recording_path as _res
            return _res()
        except Exception:
            return None

    def _resolve_recording_format(self, override: str | None = None) -> str:
        if override and isinstance(override, str) and override.strip():
            return override.strip().upper()
        try:
            from app.core.database import SessionLocal
            from app.services.camera_service import get_camera_config
            db = SessionLocal()
            try:
                cam = get_camera_config(db)
                fmt = getattr(cam, "recording_format", None)
                if fmt and isinstance(fmt, str) and fmt.strip():
                    return fmt.strip().upper()
            finally:
                db.close()
        except Exception:
            pass
        return "MP4"

    def start_recording(
        self,
        session_id: str,
        width: int,
        height: int,
        fps: float,
        root_path: str | None = None,
        recording_format: str | None = None,
        camera_settings: dict | None = None,
        camera_id: int | None = None,
        camera_name: str | None = None,
        clip_duration_minutes: int | None = None,
    ) -> str:
        from app.services.recording_service import start_recording as _start

        logger.info(f"[RECORD] Starting recording — session: {session_id} | {width}x{height} @ {fps}fps")
        realtime_log_service.add_log(
            "record",
            "RECORD",
            f"Recording started: Session {session_id}",
            "info"
        )
        if not self._is_running or not self.is_connected or self.device is None:
            raise RuntimeError("Cannot start recording: OAK camera is not running or disconnected")

        if not (self._convert_thread and self._convert_thread.is_alive()) or not (self._mjpeg_thread and self._mjpeg_thread.is_alive()):
            logger.info("[RECORD] Capture threads not running — starting them now")
            self._start_capture_threads()
        self._is_streaming = True

        resolved_format = self._resolve_recording_format(recording_format)
        resolved_path = root_path or self._resolve_recording_path()
        settings_snap = camera_settings or self._recording_settings_snapshot()

        cid = camera_id or self._active_camera_id or 1
        cname = camera_name
        clip_mins = clip_duration_minutes

        if not cname or clip_mins is None:
            try:
                from app.core.database import SessionLocal
                from app.models.camera_model import Camera
                with SessionLocal() as db_session:
                    cam_row = db_session.query(Camera).filter(Camera.id == cid).first()
                    if cam_row:
                        if not cname:
                            cname = cam_row.name
                        if clip_mins is None:
                            clip_mins = getattr(cam_row, "clip_duration_minutes", 1) or 1
            except Exception:
                pass

        cname = cname or f"Camera_{cid}"
        clip_mins = clip_mins or 1

        rec_path = _start(
            session_id=session_id,
            width=width,
            height=height,
            fps=fps,
            root_path=resolved_path,
            recording_format=resolved_format,
            camera_settings=settings_snap,
            camera_id=cid,
            camera_name=cname,
            clip_duration_minutes=clip_mins,
        )
        from app.services.recording_service import active_recordings
        self._active_recording = active_recordings.get(session_id)
        logger.info(f"[RECORD] Active recording initialized: {rec_path} (camera={cname}, format={resolved_format}, split={clip_mins}m)")
        return rec_path

    def _recording_settings_snapshot(self) -> dict:
        return {
            "exposure_us": self.current_exposure_us,
            "gain": self.current_gain,
            "focus": self.current_focus,
            "brightness": self.current_brightness,
            "contrast": self.current_contrast,
            "auto_exposure": self.auto_exposure_enabled,
            "auto_focus": self.auto_focus_enabled,
            "control_mode": self.control_mode,
        }

    def stop_recording(self, session_id: str) -> dict:
        from app.services.recording_service import stop_recording as _stop

        logger.info(f"[RECORD] Stopping recording — session: {session_id}")
        realtime_log_service.add_log(
            "record",
            "RECORD",
            f"Recording stopped: Session {session_id}",
            "success"
        )
        if self._active_recording:
            logger.info(f"[RECORD] Queue size before stop: {self._active_recording.frame_queue.qsize()}")

        self._active_recording = None
        result = _stop(session_id)
        logger.info(f"[RECORD] Recording stopped and session cleared → {result}")

        streaming_active = bool(self._is_streaming or self._stream_subscribers or (self._stream_queue is not None))
        if not streaming_active:
            logger.info("[RECORD] No active streaming — stopping capture threads")
            self._stop_capture_threads()
        else:
            logger.info(f"[RECORD] Streaming active (streaming={streaming_active}) — keeping capture threads running")

        return result

    # ==================== App Lifecycle (connect / disconnect) ====================

    async def start(self, config) -> dict:
        """App startup — connect device and build pipeline only. Does NOT start capture threads."""
        async with self._lifecycle_lock:
            if self._is_running:
                logger.info("[START] Pipeline already running")
                return {"status": "already_running"}

            try:
                self._active_camera_id = getattr(config, "id", None)
                if not self.is_connected:
                    if not await self.connect(config.ip_address):
                        err = (self._last_connection_error or "").lower()
                        is_usb = not config.ip_address or str(config.ip_address).strip().lower() in {"usb", "auto"}
                        if "already used" in err or "in use" in err or "busy" in err or "occupied" in err:
                            return {
                                "status": "error",
                                "message": self._last_connection_error or (
                                    "USB device is already in use by another application/process. Make sure to close other software using the camera."
                                    if is_usb else
                                    f"Camera at {config.ip_address} is already in use by another application or process."
                                ),
                                "error_code": "DEVICE_IN_USE",
                            }

                        if any(k in err for k in ["not found", "cannot find", "no oak", "no device", "timeout", "searched"]):
                            return {
                                "status": "error",
                                "message": self._last_connection_error or (
                                    "No OAK camera detected over USB. Please check your USB 3.0 cable connection."
                                    if is_usb else
                                    f"No OAK camera found at {config.ip_address}. Please check that the IP address is correct and reachable."
                                ),
                                "error_code": "NO_DEVICE",
                            }

                        return {
                            "status": "error",
                            "message": self._last_connection_error or f"Failed to connect to camera ({config.ip_address or 'device'})",
                            "error_code": "CONNECTION_FAILED",
                        }

                self.current_brightness = int(config.brightness or 0)
                self.current_contrast = int(config.contrast if config.contrast is not None and config.contrast != 0 else 50)

                with self._pipeline_lock:
                    self._pipeline = dai.Pipeline(self.device)

                if not self._build_pipeline(self._pipeline, config):
                    return {"status": "error", "message": "Pipeline build failed"}

                self._pipeline.start()
                self._is_running = True

                self._start_capture_threads()

                if self._legacy_preset_migration:
                    self._save_calibrated_preset()
                    self._legacy_preset_migration = False

                self._enforce_fixed_controls()

                logger.info("[START] Pipeline ready — waiting for stream/start")
                realtime_log_service.add_log(
                    "system",
                    "SYSTEM",
                    "Application initialized successfully",
                    "success"
                )

                return {"status": "started"}

            except Exception as e:
                logger.error(f"[START] Failed: {e}", exc_info=True)
                try:
                    self._cleanup_pipeline()
                    await self.disconnect()
                except Exception:
                    pass
                return {"status": "error", "message": str(e)}

    async def stop(self) -> dict:
        """App shutdown — stop capture threads if running, cleanup pipeline, disconnect device."""
        async with self._lifecycle_lock:
            try:
                if self._active_recording and getattr(self._active_recording, "session_id", None):
                    await asyncio.to_thread(self.stop_recording, self._active_recording.session_id)
                    
                self._close_stream_queue()
                self._latest_jpeg = None
                await asyncio.to_thread(self._stop_capture_threads)
                await asyncio.to_thread(self._cleanup_pipeline)
                await self.disconnect()
                logger.info("[STOP] Camera stopped")
                realtime_log_service.add_log(
                    "system",
                    "SYSTEM",
                    "Application stopped",
                    "success"
                )
                return {"status": "stopped"}
            except Exception as e:
                logger.error(f"[STOP] Failed: {e}")
                return {"status": "error", "message": str(e)}

    # ==================== Fixed-control Runtime Enforcement ====================

    def _enforce_fixed_controls(self) -> None:
        """Re-send fixed focus, exposure, brightness and contrast through the runtime control queue."""
        if not self._is_running or not self.is_connected or self._control_queue is None:
            return
        try:
            ctrl = dai.CameraControl()
            ctrl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.OFF)
            if self.current_focus is not None:
                ctrl.setManualFocus(self.current_focus)
            ctrl.setManualExposure(self.current_exposure_us, self.current_gain)
            hw_b = max(-10, min(10, int(round(self.current_brightness / 5.0))))
            hw_c = max(-10, min(10, int(round((self.current_contrast - 50) / 5.0))))
            ctrl.setBrightness(hw_b)
            ctrl.setContrast(hw_c)
            self._control_queue.send(ctrl)
            logger.info(f"[CONTROL] Fixed controls sent after pipeline startup — brightness={hw_b} contrast={hw_c}")
        except Exception as e:
            if "closed" in str(e).lower() or "xlink" in str(e).lower():
                self._on_device_lost("Control queue closed during fixed-control enforcement")
            else:
                logger.warning(f"[CONTROL] Fixed-control enforcement failed: {e}")

    # ==================== Stream Lifecycle (capture threads) ====================

    async def start_streaming(self) -> dict:
        """User clicks Start Streaming — subscribe streaming clients and ensure capture threads are active."""
        async with self._streaming_lock:
            if not self._is_running or not self.is_connected or self.device is None:
                return {"status": "error", "message": "Cannot stream: OAK camera is not connected — call /oak/start first"}

            if not self._start_capture_threads():
                return {"status": "error", "message": "Capture threads failed to start"}

            logger.info("[STREAMING] Step 1 — capture threads started / confirmed")
            self._enforce_fixed_controls()
            logger.info("[STREAMING] Step 2 — fixed camera controls enforced")

            self._is_streaming = True
            logger.info("[STREAMING] Started")
            realtime_log_service.add_log(
                "stream",
                "STREAM",
                "Video stream initialized successfully",
                "success"
            )

            return {"status": "streaming"}

    async def stop_streaming(self) -> dict:
        """User clicks Stop Streaming — close client stream queues without interrupting hardware capture."""
        async with self._streaming_lock:
            self._is_streaming = False
            self._latest_jpeg = None
            for q in list(self._stream_subscribers):
                try:
                    q.put_nowait(None)
                except Exception:
                    pass
            self._stream_subscribers.clear()
            self._stream_queue = None

            logger.info("[STREAMING] Stopped (subscribers disconnected; capture threads keep draining camera queues)")
            return {"status": "stopped"}

    def _refresh_device_detection_async(self):
        """Asynchronously probe DepthAI devices without blocking health polling."""
        if getattr(self, "_is_scanning_devices", False):
            return
        self._is_scanning_devices = True

        def _scan():
            try:
                with _depthai_device_enum_lock:
                    devs = dai.Device.getAllAvailableDevices()
                count = len(devs)
                self._cached_devices_count = count
                self._cached_device_detected = count > 0
            except Exception as e:
                logger.debug(f"[OAK PROBE] Failed checking devices: {e}")
                self._cached_devices_count = 0
                self._cached_device_detected = False
            finally:
                self._last_device_scan_time = time.time()
                self._is_scanning_devices = False

        t = threading.Thread(target=_scan, daemon=True, name="oak-device-probe")
        t.start()

    def is_device_detected(self) -> bool:
        """Check if any physical OAK / DepthAI device is present."""
        if self.is_connected and self.device is not None:
            return True
        now = time.time()
        if now - getattr(self, "_last_device_scan_time", 0.0) > 2.5 and not getattr(self, "_is_scanning_devices", False):
            self._refresh_device_detection_async()
        return getattr(self, "_cached_device_detected", False)

    # ==================== Health ====================

    def health(self) -> dict:
        is_hardware_connected = bool(self.is_connected and self.device is not None)
        device_detected = self.is_device_detected()
        return {
            "running": bool(self._is_running and is_hardware_connected),
            "connected": is_hardware_connected,
            "device_detected": device_detected,
            "devices_count": 1 if is_hardware_connected else getattr(self, "_cached_devices_count", 0),
            "camera_running": bool(self._is_running and is_hardware_connected),
            "is_running": bool(self._is_running and is_hardware_connected),
            "is_connected": is_hardware_connected,
            "mjpeg_thread": bool(self._mjpeg_thread and self._mjpeg_thread.is_alive() and is_hardware_connected),
            "hires_thread": bool(self._hires_thread and self._hires_thread.is_alive() and is_hardware_connected),
            "convert_thread": bool(self._convert_thread and self._convert_thread.is_alive() and is_hardware_connected),
            "streaming": bool(self._is_streaming and is_hardware_connected),
            "fps": round(self.current_fps, 1) if is_hardware_connected else 0.0,
            "camera_settings": self._camera_settings() if (self._is_running and is_hardware_connected) else None,
            "last_error": getattr(self, "_last_connection_error", None),
        }


class OakCameraManager:
    """Multi-camera manager for dual/multi OAK setups.
    
    Maintains independent OakCameraService instances for each camera_id.
    Delegates single-camera/default calls to the active instance for 100% backward compatibility.
    """

    def __init__(self):
        self._instances: dict[int, OakCameraService] = {}
        self._lock = threading.Lock()
        self._default_cam_id: int | None = None

    def get_instance(self, camera_id: int | None = None) -> OakCameraService:
        with self._lock:
            if camera_id is not None:
                cid = int(camera_id)
                if cid not in self._instances:
                    inst = OakCameraService()
                    inst._active_camera_id = cid
                    self._instances[cid] = inst
                return self._instances[cid]

            # If no camera_id specified:
            if self._default_cam_id is not None and self._default_cam_id in self._instances:
                return self._instances[self._default_cam_id]
            running_instances = [inst for inst in self._instances.values() if inst.is_running or inst.is_connected]
            if len(running_instances) == 1:
                return running_instances[0]
            for cid, inst in self._instances.items():
                if inst.is_running:
                    return inst
            if self._instances:
                return next(iter(self._instances.values()))

            # Create default instance at ID 1
            inst = OakCameraService()
            inst._active_camera_id = 1
            self._instances[1] = inst
            self._default_cam_id = 1
            return inst

    def get_claimed_targets(self, exclude_id: int | None = None) -> set[str]:
        claimed = set()
        with self._lock:
            for cid, inst in self._instances.items():
                if exclude_id is not None and cid == exclude_id:
                    continue
                if inst.device is not None and inst.is_connected:
                    dev_mxid = _extract_device_mxid(inst.device).lower()
                    if dev_mxid:
                        claimed.add(dev_mxid)
                    conn_mxid = getattr(inst, "_connected_mxid", None)
                    if conn_mxid:
                        claimed.add(str(conn_mxid).strip().lower())
                cip = getattr(inst, "_configured_ip", None)
                if cip:
                    claimed.add(str(cip).strip().lower())
        return claimed

    def get_claimed_mxids(self, exclude_id: int | None = None) -> set[str]:
        return self.get_claimed_targets(exclude_id)

    async def start(self, camera, camera_id: int | None = None):
        cid = camera_id or getattr(camera, "id", None) or 1
        inst = self.get_instance(cid)
        with self._lock:
            self._default_cam_id = cid
        return await inst.start(camera)

    async def stop(self, camera_id: int | None = None):
        if camera_id is not None:
            cid = int(camera_id)
            with self._lock:
                inst = self._instances.get(cid)
            if inst:
                return await inst.stop()
            return {"status": "stopped"}
        # Stop all running cameras
        results = {}
        with self._lock:
            instances = list(self._instances.items())
        for cid, inst in instances:
            if inst.is_running:
                results[cid] = await inst.stop()
        return {"status": "all_stopped", "details": results}

    def start_recording(
        self,
        session_id: str,
        width: int,
        height: int,
        fps: float,
        camera_id: int | None = None,
        **kwargs,
    ):
        inst = self.get_instance(camera_id)
        return inst.start_recording(
            session_id=session_id,
            width=width,
            height=height,
            fps=fps,
            **kwargs,
        )

    def stop_recording(self, session_id: str, camera_id: int | None = None):
        if camera_id is not None:
            inst = self.get_instance(camera_id)
            return inst.stop_recording(session_id)
        with self._lock:
            instances = list(self._instances.values())
        for inst in instances:
            if inst._active_recording and getattr(inst._active_recording, "session_id", None) == session_id:
                return inst.stop_recording(session_id)
        return self.get_instance().stop_recording(session_id)

    def get_active_recordings_count(self) -> int:
        count = 0
        with self._lock:
            for inst in self._instances.values():
                if inst._active_recording is not None:
                    count += 1
        return count

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return any(getattr(inst, "_active_recording", None) is not None for inst in self._instances.values())

    def get_all_instances(self) -> dict[int, OakCameraService]:
        with self._lock:
            return dict(self._instances)

    def health(self, camera_id: int | None = None) -> dict:
        if camera_id is not None:
            return self.get_instance(camera_id).health()
        inst = self.get_instance()
        data = inst.health()
        with self._lock:
            data["all_cameras"] = {cid: c.health() for cid, c in self._instances.items()}
        return data

    def __getattr__(self, name):
        # Forward direct attribute/method lookups to the active or default instance
        inst = self.get_instance()
        return getattr(inst, name)


oak_camera_service = OakCameraManager()
