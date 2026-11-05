# app/services/camera_service.py
# camera_service.py is mainly responsible for:
# Database Management - Stores information in SQL database.

# Creating cameras
# Updating camera settings
# Enabling/disabling cameras
# Deleting cameras
# Selecting which camera configuration should be used

# It does not directly start or stop the camera hardware.
import json
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.camera_model import Camera
from app.schemas.camera_schema import CameraCreate, CameraUpdate
from app.core.logger import setup_logger
from app.core.app_paths import APP_DIR
from app.services.realtime_log_service import realtime_log_service

import re

logger = setup_logger("camera-service")


def safe_camera_name(name: str) -> str:
    """Sanitizes camera name for OS filesystem safety, avoiding reserved names & illegal chars."""
    if not name:
        return "Camera"
    # Remove characters illegal on Windows/Linux filesystems: < > : " / \ | ? * and control chars
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', str(name))
    # Replace whitespace with underscore and strip trailing dots/spaces
    cleaned = re.sub(r'\s+', '_', cleaned.strip()).strip('.')
    # Windows reserved device names
    if cleaned.upper() in {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}:
        cleaned += "_cam"
    return cleaned[:50] or "Camera"


def normalize_name_for_comparison(n: str) -> str:
    """Normalize for duplicate checking: strips spaces, underscores, dashes, case-insensitive."""
    return re.sub(r'[\s_\-]+', '', str(n or '').strip()).lower()


# =========================================================
# CAMERA CRUD
# =========================================================

def create_camera(db: Session, data: CameraCreate):
    try:
        logger.info("[CREATE_CAMERA] Called")

        clean_name = safe_camera_name(data.name)
        norm_target = normalize_name_for_comparison(clean_name)

        # Check duplicate camera name against all existing cameras in DB
        all_cams = db.query(Camera).all()
        for c in all_cams:
            if normalize_name_for_comparison(c.name) == norm_target:
                raise HTTPException(
                    status_code=400,
                    detail=f"Camera name '{clean_name}' is already in use by another camera ('{c.name}'). Dual cameras must have different names."
                )

        dumped = data.model_dump()
        dumped["name"] = clean_name

        # Check IP address validity and uniqueness across dual cameras
        ip = (data.ip_address or "").strip()
        if ip and ip.lower() not in {"usb", "auto"}:
            import ipaddress
            try:
                ip_obj = ipaddress.IPv4Address(ip)
                clean_ip = str(ip_obj)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid IP address format: '{ip}'. Expected a valid IPv4 address (e.g. 169.254.21.191)."
                )
            for c in all_cams:
                if c.ip_address and c.ip_address.strip().lower() == clean_ip.lower():
                    raise HTTPException(
                        status_code=400,
                        detail=f"IP address '{clean_ip}' is already in use by '{c.name}'. Dual cameras must have different IP addresses."
                    )
            dumped["ip_address"] = clean_ip
        if "clip_duration_minutes" in dumped and dumped["clip_duration_minutes"]:
            dumped["clip_duration_minutes"] = max(1, int(dumped["clip_duration_minutes"]))
        else:
            dumped["clip_duration_minutes"] = 1

        if "fps" in dumped and dumped["fps"] is not None:
            dumped["fps"] = max(5, min(60, int(dumped["fps"])))
        else:
            dumped["fps"] = 30

        camera = Camera(**dumped)

        camera.exposure = camera.exposure if camera.exposure is not None else 8
        camera.gain = camera.gain if camera.gain is not None else 400
        camera.focus = camera.focus if (camera.focus is not None and camera.focus > 0) else 128
        camera.brightness = camera.brightness if camera.brightness is not None else 0
        camera.contrast = camera.contrast if camera.contrast is not None else 50
        camera.auto_exposure = False
        camera.auto_focus = False

        db.add(camera)
        db.commit()
        db.refresh(camera)

        if camera.recording_video_path:
            from app.core.app_paths import set_configured_storage_dir
            set_configured_storage_dir(camera.recording_video_path)

        logger.info(f"[CREATE_CAMERA] Created camera ID: {camera.id}")
        realtime_log_service.add_log(
            "camera",
            "CAMERA",
            f"Camera created: {camera.name}",
            "success"
        )
        return camera

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[CREATE_CAMERA] Failed error: {e}", exc_info=True)
        realtime_log_service.add_log(
            "camera",
            "ERROR",
            f"Failed to create camera: {e}",
            "error"
        )
        raise HTTPException(status_code=500, detail=f"Failed to create camera: {e}")


def update_camera_partial(db: Session, camera_id: int, data: CameraUpdate):
    try:
        logger.info(f"[UPDATE_CAMERA] Called with ID: {camera_id}")

        camera = db.query(Camera).filter(Camera.id == camera_id).first()

        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        update_data = data.model_dump(exclude_unset=True)

        # Name sanitization, duplicate check, and lock while recording
        if "name" in update_data and update_data["name"] is not None:
            clean_name = safe_camera_name(update_data["name"])
            norm_target = normalize_name_for_comparison(clean_name)
            if normalize_name_for_comparison(camera.name) != norm_target:
                # Check if camera is currently recording
                from app.services.recording_service import active_recordings
                for sid, rec in active_recordings.items():
                    if getattr(rec, "camera_id", None) == camera_id and getattr(rec, "is_running", False):
                        raise HTTPException(
                            status_code=409,
                            detail="Cannot rename camera while recording is active. Please stop recording first."
                        )
                # Check duplicate across all other cameras in DB
                all_cams = db.query(Camera).filter(Camera.id != camera_id).all()
                for c in all_cams:
                    if normalize_name_for_comparison(c.name) == norm_target:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Camera name '{clean_name}' is already in use by another camera ('{c.name}'). Dual cameras must have different names."
                        )
            update_data["name"] = clean_name

        if "ip_address" in update_data and update_data["ip_address"] is not None:
            new_ip = str(update_data["ip_address"] or "").strip()
            if new_ip and new_ip.lower() not in {"usb", "auto"}:
                import ipaddress
                try:
                    ip_obj = ipaddress.IPv4Address(new_ip)
                    clean_ip = str(ip_obj)
                except Exception:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid IP address format: '{new_ip}'. Expected a valid IPv4 address (e.g. 169.254.21.191)."
                    )
                all_cams = db.query(Camera).filter(Camera.id != camera_id).all()
                for c in all_cams:
                    if c.ip_address and c.ip_address.strip().lower() == clean_ip.lower():
                        raise HTTPException(
                            status_code=400,
                            detail=f"IP address '{clean_ip}' is already in use by '{c.name}'. Dual cameras must have different IP addresses."
                        )
                update_data["ip_address"] = clean_ip

        if "clip_duration_minutes" in update_data and update_data["clip_duration_minutes"] is not None:
            update_data["clip_duration_minutes"] = max(1, int(update_data["clip_duration_minutes"]))

        if "fps" in update_data and update_data["fps"] is not None:
            update_data["fps"] = max(5, min(60, int(update_data["fps"])))

        for key, value in update_data.items():
            setattr(camera, key, value)

        if "recording_video_path" in update_data and update_data["recording_video_path"]:
            from app.core.app_paths import set_configured_storage_dir
            set_configured_storage_dir(update_data["recording_video_path"])

        if camera.exposure is None:
            camera.exposure = 8
        if camera.gain is None:
            camera.gain = 400
        if camera.focus is None or camera.focus <= 0:
            camera.focus = 128
        if camera.brightness is None:
            camera.brightness = 0
        if camera.contrast is None:
            camera.contrast = 50
        if camera.auto_exposure is None:
            camera.auto_exposure = False
        if camera.auto_focus is None:
            camera.auto_focus = False

        db.commit()
        db.refresh(camera)

        # Sync runtime controls to physical OAK camera if pipeline is currently active
        try:
            from app.services.oak_camera_service import oak_camera_service
            inst = oak_camera_service.get_instance(camera_id)
            if inst.is_running:
                inst.update_controls(
                    exposure=camera.exposure,
                    gain=camera.gain,
                    focus=camera.focus,
                    brightness=camera.brightness,
                    contrast=camera.contrast,
                    control_mode=camera.control_mode,
                )
        except Exception as sync_err:
            logger.debug(f"[UPDATE_CAMERA] Dynamic control sync skipped: {sync_err}")

        logger.info("[UPDATE_CAMERA] Success")
        realtime_log_service.add_log(
            "camera",
            "CAMERA",
            f"Camera updated: ID {camera_id}",
            "success"
        )
        return camera

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[UPDATE_CAMERA] Failed error: {e}", exc_info=True)
        realtime_log_service.add_log(
            "camera",
            "ERROR",
            f"Update camera failed: {e}",
            "error"
        )
        raise HTTPException(status_code=500, detail=f"Failed to update camera: {e}")


def enable_camera(db: Session, camera_id: int):
    try:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        camera.is_enabled = True
        db.commit()
        db.refresh(camera)
        realtime_log_service.add_log(
            "camera",
            "CAMERA",
            f"Camera enabled: ID {camera_id}",
            "success"
        )
        return camera

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[ENABLE_CAMERA] Failed error: {e}", exc_info=True)
        realtime_log_service.add_log(
            "camera",
            "ERROR",
            f"Enable failed - ID {camera_id}: {e}",
            "error"
        )
        raise HTTPException(status_code=500, detail=f"Failed to enable camera: {e}")


def disable_camera(db: Session, camera_id: int):
    try:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        camera.is_enabled = False
        db.commit()
        db.refresh(camera)
        realtime_log_service.add_log(
            "camera",
            "CAMERA",
            f"Camera disabled: ID {camera_id}",
            "success"
        )
        return camera

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[DISABLE_CAMERA] Failed error: {e}", exc_info=True)
        realtime_log_service.add_log(
            "camera",
            "ERROR",
            f"Disable failed - ID {camera_id}: {e}",
            "error"
        )
        raise HTTPException(status_code=500, detail=f"Failed to disable camera: {e}")


def delete_camera(db: Session, camera_id: int):
    try:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        db.delete(camera)
        db.commit()
        realtime_log_service.add_log(
            "camera",
            "CAMERA",
            f"Camera deleted: ID {camera_id}",
            "success"
        )
        return {"status": "success", "message": f"Camera {camera_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[DELETE_CAMERA] Failed error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def get_cameras(db: Session):
    return db.query(Camera).all()


def get_camera_config(db: Session):
    # 1. Prefer real enabled hardware cameras (exclude mock 127.0.0.1)
    real_cam = (
        db.query(Camera)
        .filter(
            Camera.ip_address.isnot(None),
            Camera.ip_address != "127.0.0.1",
            Camera.is_enabled == True,
        )
        .order_by(Camera.id.desc())
        .first()
    )
    if real_cam:
        return real_cam

    # 2. Fallback to any enabled camera
    enabled_cam = (
        db.query(Camera)
        .filter(Camera.is_enabled == True)
        .order_by(Camera.id.desc())
        .first()
    )
    if enabled_cam:
        return enabled_cam

    # 3. Fallback to newest camera
    return db.query(Camera).order_by(Camera.id.desc()).first()



