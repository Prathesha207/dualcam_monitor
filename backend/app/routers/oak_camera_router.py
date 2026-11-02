import asyncio
import logging
import time
from typing import Optional

import cv2
import numpy as np
import depthai as dai
from fastapi import APIRouter, Depends, Request, HTTPException, Body
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.camera_model import Camera
from app.services import camera_service
from app.services.oak_camera_service import oak_camera_service
from app.services.realtime_log_service import realtime_log_service

logger = logging.getLogger("oak-camera")

router = APIRouter()

# Prevents concurrent /oak/start requests from racing into DepthAI
# device enumeration simultaneously — the XLink native layer segfaults
# when getAllAvailableDevices() is called from multiple threads at once.
_start_lock = asyncio.Lock()


class StartCameraPayload(BaseModel):
    camera_id: Optional[int] = None
    ip_address: Optional[str] = None


# ==================== App Lifecycle ====================

@router.post("/start")
async def start_camera(payload: Optional[StartCameraPayload] = None, db: Session = Depends(get_db)):
    """App startup — connect device and build pipeline."""
    if _start_lock.locked():
        logger.info("[API] POST /oak/start — already in progress, skipping duplicate request")
        return {"status": "already_starting", "message": "Camera start already in progress"}

    async with _start_lock:
        camera = None
        if payload and payload.camera_id:
            camera = db.query(Camera).filter(Camera.id == payload.camera_id).first()
        elif payload and payload.ip_address:
            camera = db.query(Camera).filter(Camera.ip_address == payload.ip_address).first()

        if not camera:
            camera = camera_service.get_camera_config(db)

        if not camera or not camera.ip_address:
            try:
                loop = asyncio.get_running_loop()
                device_info = await loop.run_in_executor(None, oak_camera_service._resolve_device_info, "usb")
                mxid = str(getattr(device_info, "mxid", "") or "")
                if not mxid:
                    mxid = "usb"
                
                if not camera:
                    from app.schemas.camera_schema import CameraCreate
                    new_cam = CameraCreate(name="Auto USB Camera", ip_address=mxid, control_mode="auto")
                    camera = camera_service.create_camera(db, new_cam)
                else:
                    from app.schemas.camera_schema import CameraUpdate
                    camera = camera_service.update_camera_partial(db, camera.id, CameraUpdate(ip_address=mxid))
            except Exception as e:
                logger.warning(f"[OAK DEVICE ENUM] {e}")
                realtime_log_service.add_log("camera", "WARN", f"No camera connected: {e}", "warning")
                return {"status": "error", "message": f"No camera connected: {str(e)}"}

        try:
            cid = getattr(payload, "camera_id", None) or getattr(camera, "id", None)
            result = await oak_camera_service.start(camera, camera_id=cid)
            return result
        except Exception as e:
            logger.error(f"[API ERROR] POST /oak/start: {e}", exc_info=True)
            realtime_log_service.add_log("camera", "CRASH", f"Start camera failed: {e}", "error")
            raise HTTPException(status_code=500, detail=f"Failed to start camera: {e}")


@router.post("/stop")
async def stop_camera(payload: Optional[StartCameraPayload] = None, camera_id: Optional[int] = None):
    """App shutdown — stop everything and disconnect."""
    try:
        cid = camera_id or (payload.camera_id if payload else None)
        result = await oak_camera_service.stop(camera_id=cid)
        return result
    except Exception as e:
        logger.error(f"[API ERROR] POST /oak/stop: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "CRASH", f"Stop camera failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Failed to stop camera: {e}")


# ==================== Stream Lifecycle ====================

@router.post("/stream/start")
async def start_stream(payload: Optional[StartCameraPayload] = None, camera_id: Optional[int] = None):
    """User clicks Start Streaming — starts the capture threads."""
    try:
        cid = camera_id or (payload.camera_id if payload else None)
        inst = oak_camera_service.get_instance(cid)
        result = await inst.start_streaming()
        return result
    except Exception as e:
        logger.error(f"[API ERROR] POST /oak/stream/start: {e}", exc_info=True)
        realtime_log_service.add_log("stream", "CRASH", f"Start stream failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Failed to start stream: {e}")


@router.post("/stream/stop")
async def stop_stream(payload: Optional[StartCameraPayload] = None, camera_id: Optional[int] = None):
    """User clicks Stop Streaming — stops streaming subscribers."""
    try:
        cid = camera_id or (payload.camera_id if payload else None)
        inst = oak_camera_service.get_instance(cid)
        result = await inst.stop_streaming()
        return result
    except Exception as e:
        logger.error(f"[API ERROR] POST /oak/stream/stop: {e}", exc_info=True)
        realtime_log_service.add_log("stream", "CRASH", f"Stop stream failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Failed to stop stream: {e}")


# ==================== MJPEG Stream ====================

async def _serve_mjpeg(request: Request, camera_id: Optional[int] = None, db: Session = None):
    inst = oak_camera_service.get_instance(camera_id)
    if not inst._is_running:
        _last_auto_start_attempt = getattr(inst, "_last_auto_start_attempt", 0)
        if time.time() - _last_auto_start_attempt > 10 and db is not None:
            inst._last_auto_start_attempt = time.time()
            try:
                cam = None
                if camera_id:
                    cam = db.query(Camera).filter(Camera.id == camera_id).first()
                if not cam:
                    cam = camera_service.get_camera_config(db)
                if cam:
                    logger.info(f"[STREAM] Auto-starting camera ID {cam.id} ({cam.ip_address}) for stream")
                    await inst.start(cam)
            except Exception as e:
                logger.warning(f"[STREAM] Auto-start camera failed: {e}")

    if not inst._is_running:
        return Response(
            content=b"Camera not started",
            status_code=503,
            media_type="text/plain",
        )

    if inst._is_running and inst.is_connected:
        if not (inst._mjpeg_thread and inst._mjpeg_thread.is_alive()):
            logger.info(f"[STREAM] Capture threads not running for cam {camera_id} — starting them now")
            inst._start_capture_threads()

    inst._is_streaming = True
    client_queue = inst.subscribe_stream()

    async def generate():
        frames_sent = 0
        start_time = time.time()

        try:
            while True:
                if await request.is_disconnected():
                    logger.info(f"[STREAM] Client disconnected (cam {camera_id}) — frames sent: {frames_sent}")
                    break

                if not inst._is_streaming or not inst._is_running or not inst.is_connected:
                    logger.info(f"[STREAM] Stream stopped or camera disconnected (cam {camera_id})")
                    break

                try:
                    jpeg = await asyncio.wait_for(client_queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    if not inst._is_running or not inst._is_streaming or not inst.is_connected:
                        break
                    if (
                        inst._is_streaming
                        and inst._is_running
                        and inst.is_connected
                        and inst._mjpeg_dai_queue is not None
                        and not (inst._mjpeg_thread and inst._mjpeg_thread.is_alive())
                    ):
                        logger.info(f"[STREAM] Attempting to restart capture threads for cam {camera_id}")
                        inst._start_capture_threads()
                    continue

                if jpeg is None:
                    break

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + jpeg +
                    b"\r\n"
                )

                frames_sent += 1

        except (asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as e:
            logger.error(f"[STREAM] Generator error (cam {camera_id}): {e}")
        finally:
            inst.unsubscribe_stream(client_queue)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "close",
        },
    )


@router.get("/stream")
async def stream(request: Request, camera_id: Optional[int] = None, db: Session = Depends(get_db)):
    """MJPEG HTTP stream — connect to this after stream/start or on canvas load."""
    return await _serve_mjpeg(request, camera_id=camera_id, db=db)


@router.get("/stream/{camera_id}")
async def stream_by_id(request: Request, camera_id: int, db: Session = Depends(get_db)):
    """MJPEG HTTP stream for a specific camera ID."""
    return await _serve_mjpeg(request, camera_id=camera_id, db=db)


# ==================== Snapshot ====================

@router.get("/snapshot")
async def snapshot(camera_id: Optional[int] = None):
    """Single JPEG frame for snapshot."""
    inst = oak_camera_service.get_instance(camera_id)
    if inst._latest_jpeg is not None:
        return Response(content=inst._latest_jpeg, media_type="image/jpeg")

    frame = await inst.get_stream_frame(timeout=0.5)
    if frame is not None:
        return Response(content=frame, media_type="image/jpeg")

    bgr = inst.get_bgr_frame()
    if bgr is not None:
        loop = asyncio.get_running_loop()
        def _enc():
            s, b = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return b.tobytes() if s else None
        buf = await loop.run_in_executor(None, _enc)
        if buf is not None:
            return Response(content=buf, media_type="image/jpeg")

    if inst._mjpeg_thread and inst._mjpeg_thread.is_alive():
        frame = await inst.get_stream_frame(timeout=1.0)
        if frame is not None:
            return Response(content=frame, media_type="image/jpeg")

    blank = np.zeros((720, 1280, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", blank, [cv2.IMWRITE_JPEG_QUALITY, 50])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.get("/snapshot/{camera_id}")
async def snapshot_by_id(camera_id: int):
    return await snapshot(camera_id=camera_id)


# ==================== Health & Devices ====================

@router.get("/health")
def health():
    return oak_camera_service.health()


@router.get("/devices")
async def get_available_devices():
    """Discover connected Luxonis OAK-D devices over USB and Network."""
    devices = []
    loop = asyncio.get_running_loop()
    try:
        from app.services.oak_camera_service import _depthai_device_enum_lock

        def _enum_devices():
            with _depthai_device_enum_lock:
                return dai.Device.getAllAvailableDevices()

        raw_devices = await loop.run_in_executor(None, _enum_devices)
        for d in raw_devices:
            mxid = str(getattr(d, "mxid", "") or "")
            name = str(getattr(d, "name", "") or "")
            protocol = str(getattr(d, "protocol", "") or "")
            state = str(getattr(d, "state", "") or "")
            desc_name = ""
            try:
                desc = d.getXLinkDeviceDesc()
                desc_name = str(getattr(desc, "name", "") or "")
            except Exception:
                pass
            is_usb = "usb" in protocol.lower() or "usb" in name.lower() or "usb" in state.lower()
            devices.append({
                "mxid": mxid,
                "name": desc_name or name or (f"OAK USB ({mxid[:8]})" if is_usb else f"OAK Network ({mxid[:8]})"),
                "ip_or_id": mxid if is_usb else (desc_name or name or mxid),
                "protocol": "USB" if is_usb else "TCP/IP",
                "state": state,
                "is_usb": is_usb,
            })
    except Exception as e:
        logger.warning(f"[DEVICES] Failed to enumerate DepthAI devices: {e}")
    return devices


# ==================== Camera Hardware Calibration & Intrinsics ====================

@router.get("/calibration")
def get_camera_calibration():
    """Read genuine hardware calibration matrix and intrinsics from OAK-D camera EEPROM."""
    try:
        res = oak_camera_service.get_hardware_calibration()
        if res.get("status") == "error":
            raise HTTPException(status_code=404, detail=res.get("message"))
        return res
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get hardware calibration")
        raise HTTPException(status_code=500, detail=f"Failed to read camera calibration: {e}")


@router.get("/calibration/yaml")
def get_camera_calibration_yaml():
    """Returns the exact CAMERA_MATRIX YAML text representation directly."""
    try:
        res = oak_camera_service.get_hardware_calibration()
        if res.get("status") == "error":
            raise HTTPException(status_code=404, detail=res.get("message"))
        return Response(content=res.get("yaml_string", ""), media_type="text/yaml")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get hardware calibration YAML")
        raise HTTPException(status_code=500, detail=f"Failed to read camera calibration: {e}")


# ==================== Camera Controls ====================

@router.post("/controls/calibrate")
def calibrate_camera_controls():
    try:
        return oak_camera_service.calibrate_auto_controls()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("Camera calibration failed")
        raise HTTPException(status_code=500, detail=f"Camera calibration failed: {e}")


class CameraControlsRequest(BaseModel):
    control_mode: Optional[str] = None
    exposure: Optional[int] = None
    gain: Optional[int] = None
    focus: Optional[int] = None
    brightness: Optional[int] = None
    contrast: Optional[int] = None
    auto_focus: Optional[bool] = None
    autoFocus: Optional[bool] = None
    auto_exposure: Optional[bool] = None
    autoExposure: Optional[bool] = None
    reset: Optional[bool] = None
    save_to_db: Optional[bool] = None


@router.post("/controls/reset")
def reset_camera_controls():
    """Apply the saved preset from database."""
    try:
        return oak_camera_service.reset_controls()
    except Exception as e:
        logger.error(f"[API ERROR] POST /oak/controls/reset: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "CRASH", f"Camera controls reset failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Failed to reset controls: {e}")


@router.post("/controls/save")
def save_camera_controls():
    """Save the current active runtime camera controls directly to the database."""
    try:
        return oak_camera_service.save_current_controls_to_db(control_mode="manual")
    except Exception as e:
        logger.error(f"[API ERROR] POST /oak/controls/save: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "ERROR", f"Failed to save camera controls: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Failed to save camera controls to database: {e}")


@router.post("/controls")
def update_controls(
    body: Optional[CameraControlsRequest] = Body(default=None),
    control_mode: str | None = None,
    exposure: int | None = None,
    gain: int | None = None,
    focus: int | None = None,
    brightness: int | None = None,
    contrast: int | None = None,
    auto_focus: bool | None = None,
    auto_exposure: bool | None = None,
    reset: bool | None = None,
    save_to_db: bool | None = None,
):
    try:
        is_reset = (body.reset if body and body.reset is not None else reset)
        if is_reset:
            return oak_camera_service.reset_controls()

        exp = body.exposure if body and body.exposure is not None else exposure
        g = body.gain if body and body.gain is not None else gain
        f = body.focus if body and body.focus is not None else focus
        b = body.brightness if body and body.brightness is not None else brightness
        c = body.contrast if body and body.contrast is not None else contrast
        mode = body.control_mode if body and body.control_mode is not None else control_mode
        af = (body.auto_focus if body and body.auto_focus is not None else (body.autoFocus if body and body.autoFocus is not None else auto_focus))
        ae = (body.auto_exposure if body and body.auto_exposure is not None else (body.autoExposure if body and body.autoExposure is not None else auto_exposure))
        should_save = (body.save_to_db if body and body.save_to_db is not None else save_to_db)

        oak_camera_service.update_controls(
            exposure=exp,
            gain=g,
            focus=f,
            brightness=b,
            contrast=c,
            auto_focus=af,
            auto_exposure=ae,
            control_mode=mode,
            reset=is_reset,
        )

        if should_save:
            oak_camera_service.save_current_controls_to_db(control_mode=mode or "manual")

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API ERROR] POST /oak/controls: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "CRASH", f"Camera controls update failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Failed to update controls: {e}")
