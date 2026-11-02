# app/services/camera_service.py

import json
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.camera_model import Camera
from app.schemas.camera_schema import CameraCreate, CameraUpdate
from app.core.logger import setup_logger
from app.core.app_paths import APP_DIR
from app.services.realtime_log_service import realtime_log_service

logger = setup_logger("camera-service")


# =========================================================
# CAMERA CRUD
# =========================================================

def create_camera(db: Session, data: CameraCreate):
    try:
        logger.info("[CREATE_CAMERA] Called")

        camera = Camera(**data.model_dump())

        camera.exposure = camera.exposure if camera.exposure is not None else 8
        camera.gain = camera.gain if camera.gain is not None else 400
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

        for key, value in update_data.items():
            setattr(camera, key, value)

        if "recording_video_path" in update_data and update_data["recording_video_path"]:
            from app.core.app_paths import set_configured_storage_dir
            set_configured_storage_dir(update_data["recording_video_path"])

        if camera.exposure is None:
            camera.exposure = 8
        if camera.gain is None:
            camera.gain = 400
        if camera.auto_exposure is None:
            camera.auto_exposure = False
        if camera.auto_focus is None:
            camera.auto_focus = False

        db.commit()
        db.refresh(camera)

        # Sync runtime controls to physical OAK camera if pipeline is currently active
        try:
            from app.services.oak_camera_service import oak_camera_service
            if oak_camera_service.is_running:
                oak_camera_service.update_controls(
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



