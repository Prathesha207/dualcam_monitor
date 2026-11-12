import os
import logging
import cv2

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.recording_schema import StartRecordingRequest, StopRecordingRequest
from app.services import camera_service
from app.services.oak_camera_service import oak_camera_service
from app.services.realtime_log_service import realtime_log_service

logger = logging.getLogger("recording-api")

router = APIRouter()


@router.post("/start")
async def start_recording(data: StartRecordingRequest, db: Session = Depends(get_db)):
    cam_id = data.camera_id
    cam_inst = oak_camera_service.get_instance(cam_id)

    camera_config = None
    if cam_id:
        from app.models.camera_model import Camera
        camera_config = db.query(Camera).filter(Camera.id == cam_id).first()
    if not camera_config:
        camera_config = camera_service.get_camera_config(db)

    if not cam_inst.is_connected or not cam_inst._is_running or cam_inst.device is None:
        if camera_config and camera_config.is_enabled is not False:
            logger.info(f"[RECORD] Camera {cam_id or camera_config.id} pipeline not running — auto-starting camera device for recording")
            try:
                await cam_inst.start(camera_config)
                cam_inst._start_capture_threads()
                cam_inst._is_streaming = True
            except Exception as e:
                logger.error(f"[RECORD] Auto-start camera {cam_id or camera_config.id} failed: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to auto-start camera for recording: {e}"
                )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot start recording: Camera {cam_id or ''} is disabled or config not found."
            )

    try:
        if not camera_config:
            raise HTTPException(status_code=404, detail="Camera config not found")

        resolution = camera_config.resolution or "1920x1080"
        try:
            sep = "x" if "x" in resolution else "*"
            width, height = map(int, resolution.split(sep))
        except Exception:
            logger.warning(f"[RECORD] Invalid resolution '{resolution}' — fallback 1920x1080")
            width, height = 1920, 1080

        custom_root_path = camera_config.recording_video_path or None
        if not custom_root_path or not os.path.exists(custom_root_path):
            from app.core.app_paths import get_configured_storage_dir
            custom_root_path = str(get_configured_storage_dir())

        camera_name = camera_config.name if camera_config else f"Camera_{cam_id or 1}"
        clip_mins = data.clip_duration_minutes or getattr(camera_config, "clip_duration_minutes", 1) or 1

        path = cam_inst.start_recording(
            session_id=data.session_id,
            width=width,
            height=height,
            fps=float(camera_config.fps or 30),
            root_path=custom_root_path,
            recording_format=data.recording_format or camera_config.recording_format,
            camera_settings=cam_inst._recording_settings_snapshot(),
            camera_id=cam_id or camera_config.id,
            camera_name=camera_name,
            clip_duration_minutes=clip_mins,
        )
        return {
            "status": "recording",
            "session_id": data.session_id,
            "camera_id": cam_id or camera_config.id,
            "recording_path": path,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        logger.warning(f"[API ERROR] POST /recording/start failed: {e}")
        realtime_log_service.add_log("record", "ERROR", str(e), "error")
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"[API ERROR] POST /recording/start failed: {e}", exc_info=True)
        realtime_log_service.add_log("record", "CRASH", f"Start recording failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Internal error starting recording: {e}")


@router.post("/stop")
def stop_recording(data: StopRecordingRequest):
    try:
        result = oak_camera_service.stop_recording(data.session_id, camera_id=data.camera_id)
        session_dir = result.get("session_dir", "")
        clips = result.get("clips", [])

        # Use the last clip's path as the representative recording path.
        # Fall back to the first clip, then the session dir itself.
        if clips:
            video_path = clips[-1].get("path", "")
            if not os.path.exists(video_path) and len(clips) > 0:
                video_path = clips[0].get("path", "")
        else:
            video_path = result.get("recording_path", "")

        # Validate: at minimum the session folder must exist
        if not session_dir or not os.path.isdir(session_dir):
            logger.warning(f"[RECORD] Session dir not found on stop: {session_dir}")
            raise HTTPException(status_code=404, detail="Recording session ended but file was not found")

        if video_path and not os.path.exists(video_path):
            # File may still be named _temp (encoder crash) — try the session dir listing
            import glob
            candidates = glob.glob(os.path.join(session_dir, f"clip*{result.get('format', '.mp4').lower()}"))
            if not candidates:
                candidates = glob.glob(os.path.join(session_dir, "clip*"))
            if candidates:
                video_path = sorted(candidates)[-1]
                logger.warning(f"[RECORD] Primary path missing, using fallback: {video_path}")
            else:
                logger.warning(f"[RECORD] File not found on stop: {video_path}")
                raise HTTPException(status_code=404, detail="Recording session ended but file was not found")

        filename = result.get("filename", os.path.basename(video_path) if video_path else "recording")
        logger.info(f"[RECORD] Successfully finalized {filename} at {video_path}")

        return {
            "status": "done",
            "session_id": data.session_id,
            "recording_session_id": data.session_id,
            "camera_id": data.camera_id,
            "recording_path": video_path,
            "filename": filename,
            "duration": result.get("duration", 0),
            "frames": result.get("frames_written", 0),
            "width": result.get("width", 1920),
            "height": result.get("height", 1080),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API ERROR] POST /recording/stop failed: {e}", exc_info=True)
        realtime_log_service.add_log("record", "CRASH", f"Stop recording failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Internal error stopping recording: {e}")


@router.post("/start-all")
async def start_all_recordings(data: StartRecordingRequest, db: Session = Depends(get_db)):
    """Start recording synchronously across all active running cameras (auto-starting enabled ones)."""
    from app.models.camera_model import Camera
    all_cams = db.query(Camera).filter(Camera.is_enabled != False).all()
    for cam_row in all_cams:
        inst = oak_camera_service.get_instance(cam_row.id)
        if not inst.is_running or not inst.is_connected:
            try:
                await inst.start(cam_row)
                inst._start_capture_threads()
                inst._is_streaming = True
            except Exception as e:
                logger.warning(f"[RECORD-ALL] Auto-start for cam {cam_row.id} failed: {e}")

    active_instances = oak_camera_service.get_all_instances()
    running_cams = {cid: inst for cid, inst in active_instances.items() if inst.is_running and inst.is_connected}

    if not running_cams:
        raise HTTPException(status_code=400, detail="No active streaming cameras available to record")

    results = {}
    base_session_id = data.session_id
    for cid, inst in running_cams.items():
        cam_session_id = f"{base_session_id}_cam{cid}"
        camera_config = db.query(Camera).filter(Camera.id == cid).first()
        res = camera_config.resolution if camera_config else "1920x1080"
        try:
            sep = "x" if "x" in res else "*"
            width, height = map(int, res.split(sep))
        except Exception:
            width, height = 1920, 1080

        root_path = getattr(camera_config, "recording_video_path", None)
        if not root_path or not os.path.exists(root_path):
            from app.core.app_paths import get_configured_storage_dir
            root_path = str(get_configured_storage_dir())
        fmt = data.recording_format or getattr(camera_config, "recording_format", "MP4")
        fps = float(getattr(camera_config, "fps", 30) or 30)

        cam_name = camera_config.name if camera_config else f"Camera_{cid}"
        clip_mins = getattr(camera_config, "clip_duration_minutes", 1) or 1

        path = inst.start_recording(
            session_id=cam_session_id,
            width=width,
            height=height,
            fps=fps,
            root_path=root_path,
            recording_format=fmt,
            camera_settings=inst._recording_settings_snapshot(),
            camera_id=cid,
            camera_name=cam_name,
            clip_duration_minutes=clip_mins,
        )
        results[cid] = {
            "session_id": cam_session_id,
            "recording_path": path,
        }

    return {
        "status": "recording_all",
        "base_session_id": base_session_id,
        "sessions": results,
    }


@router.post("/stop-all")
def stop_all_recordings():
    """Stop all active recordings across all cameras."""
    from app.services.recording_service import active_recordings
    results = {}
    for session_id in list(active_recordings.keys()):
        try:
            res = oak_camera_service.stop_recording(session_id)
            results[session_id] = res
        except Exception as e:
            logger.error(f"[RECORD] Failed stopping session {session_id}: {e}")
            results[session_id] = {"status": "error", "message": str(e)}

    return {
        "status": "all_stopped",
        "recordings": results,
    }


@router.get("/status")
def recording_status():
    try:
        from app.services.recording_service import active_recordings
        active = oak_camera_service._active_recording is not None
        return {
            "is_recording": active,
            "active_count": len(active_recordings),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API ERROR] GET /recording/status failed: {e}", exc_info=True)
        realtime_log_service.add_log("record", "CRASH", f"Recording status check failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Internal error checking recording status: {e}")
